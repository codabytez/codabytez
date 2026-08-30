"""
Builds the GitHub profile card.

Queries the GitHub GraphQL API for repository, commit, star, follower and
line-of-code totals, caches the expensive per-repository walk, and hands the
results to `render.py`.

    ACCESS_TOKEN=$(gh auth token) python today.py

Originally by Andrew Grant (Andrew6rant), 2022-2025.

The token needs a fine-grained PAT with All Repositories access:
  Account permissions:    read:Followers, read:Starring, read:Watching
  Repository permissions: read:Commit statuses, read:Contents, read:Metadata,
                          read:Issues, read:Pull Requests
"""

import datetime
import hashlib
import os
import re
import sys
import time

import requests
from dateutil import relativedelta

import config
import render


def load_dotenv(*paths):
    """
    Read KEY=value pairs from dotenv files, for running this locally.

    Reads `.env.local` before `.env`, and a real environment variable beats
    both. `.env` is the Python convention and the one to use; `.env.local` is
    accepted only because it is muscle memory for anyone coming from
    Next.js or Vite, where `.env` is committed and `.local` holds the secrets.
    Without this, a token written to `.env.local` would be silently ignored.
    Both are gitignored.
    """
    for path in paths or ('.env.local', '.env'):
        if not os.path.exists(path):
            continue
        with open(path, encoding='utf-8') as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                key, value = line.split('=', 1)
                value = value.strip().strip('"').strip("'")
                if value:  # a blank placeholder must not mask a real env var
                    os.environ.setdefault(key.strip(), value)


load_dotenv()

TOKEN = os.environ.get('ACCESS_TOKEN') or os.environ.get('GITHUB_TOKEN')
if not TOKEN:
    sys.exit(
        'No GitHub token found.\n'
        '  Locally:  ACCESS_TOKEN=$(gh auth token) python today.py\n'
        '            ...or put ACCESS_TOKEN=... in a .env file\n'
        '  In CI:    set the ACCESS_TOKEN repository secret'
    )

HEADERS = {'authorization': 'token ' + TOKEN}
USER_NAME = config.USER_NAME
# {'id': <node id>} once user_getter has run; compared directly against
# each commit's author.user, which GitHub returns in the same shape.
OWNER_ID: dict = {}

QUERY_COUNT = {'user_getter': 0, 'follower_getter': 0, 'graph_repos_stars': 0,
               'recursive_loc': 0, 'loc_query': 0,
               'language_getter': 0, 'contribution_graph': 0, 'branch_commits': 0}


def daily_readme(start):
    """
    Returns the length of time since `start`
    e.g. 'XX years, XX months, XX days'
    """
    diff = relativedelta.relativedelta(datetime.datetime.today(), start)
    return '{} {}, {} {}, {} {}{}'.format(
        diff.years, 'year' + format_plural(diff.years),
        diff.months, 'month' + format_plural(diff.months),
        diff.days, 'day' + format_plural(diff.days),
        ' 🎂' if (diff.months == 0 and diff.days == 0) else '')


def format_plural(unit):
    """
    Returns a properly formatted number
    e.g.
    'day' + format_plural(diff.days) == 5
    >>> '5 days'
    'day' + format_plural(diff.days) == 1
    >>> '1 day'
    """
    return 's' if unit != 1 else ''


# 499 is GitHub abandoning a GraphQL query that ran too long server-side; it
# shows up on repositories with deep commit histories and succeeds on a retry.
TRANSIENT_STATUS = (408, 429, 499, 500, 502, 503, 504)


def post_graphql(query, variables, retries=5):
    """
    POSTs to the GraphQL API, retrying transient upstream failures with an
    exponential backoff. GitHub serves 502s and 499s often enough that a single
    hiccup used to abort the whole run.

    Always returns a Response or raises - never None. The previous version fell
    off the end of the loop and returned None implicitly, which every caller
    then dereferenced as `.status_code` or `.json()`.
    """
    attempts = max(1, retries)
    delay = 2
    response = None
    failure = None
    for attempt in range(attempts):
        response, failure = None, None
        try:
            response = requests.post('https://api.github.com/graphql', json={'query': query, 'variables': variables}, headers=HEADERS, timeout=30)
        except requests.exceptions.RequestException as error:
            failure = error
        else:
            if response.status_code not in TRANSIENT_STATUS:
                return response
        if attempt == attempts - 1:
            break
        wait = delay
        if response is not None:
            try: wait = max(wait, int(response.headers.get('Retry-After', 0)))
            except (TypeError, ValueError): pass
        print('   transient failure, retrying in {}s ({}/{})'.format(wait, attempt + 1, attempts - 1))
        time.sleep(wait)
        delay *= 2
    if response is not None:
        return response  # retries exhausted on a transient status - let the caller report it
    if failure is not None:
        raise failure
    raise RuntimeError('no response from the GitHub API')


def simple_request(func_name, query, variables):
    """
    Returns a request, or raises an Exception if the response does not succeed.
    """
    request = post_graphql(query, variables)
    if request.status_code == 200:
        return request
    raise Exception(func_name, ' has failed with a', request.status_code, request.text, QUERY_COUNT)


def graph_repos_stars(count_type, owner_affiliation, cursor=None):
    """
    Uses GitHub's GraphQL API to return my total repository, star, or lines of code count.
    """
    query_count('graph_repos_stars')
    query = '''
    query ($owner_affiliation: [RepositoryAffiliation], $login: String!, $cursor: String) {
        user(login: $login) {
            repositories(first: 100, after: $cursor, ownerAffiliations: $owner_affiliation) {
                totalCount
                edges {
                    node {
                        ... on Repository {
                            nameWithOwner
                            stargazers {
                                totalCount
                            }
                        }
                    }
                }
                pageInfo {
                    endCursor
                    hasNextPage
                }
            }
        }
    }'''
    variables = {'owner_affiliation': owner_affiliation, 'login': USER_NAME, 'cursor': cursor}
    request = simple_request(graph_repos_stars.__name__, query, variables)
    if count_type == 'repos':
        return request.json()['data']['user']['repositories']['totalCount']
    elif count_type == 'stars':
        return stars_counter(request.json()['data']['user']['repositories']['edges'])


def language_getter(cursor=None, repos=None):
    """
    Uses GitHub's GraphQL API to fetch the language byte counts of every
    non-fork repository I have access to, organisation and collaborator repos
    included. Returns [(nameWithOwner, {language: bytes})] rather than a single
    total, because which repos count is decided later - see language_stats().
    """
    query_count('language_getter')
    repos = [] if repos is None else repos
    query = '''
    query ($login: String!, $cursor: String, $owner_affiliation: [RepositoryAffiliation]) {
        user(login: $login) {
            repositories(first: 100, after: $cursor, ownerAffiliations: $owner_affiliation, isFork: false) {
                nodes {
                    nameWithOwner
                    languages(first: 15, orderBy: {field: SIZE, direction: DESC}) {
                        edges {
                            size
                            node {
                                name
                            }
                        }
                    }
                }
                pageInfo {
                    endCursor
                    hasNextPage
                }
            }
        }
    }'''
    variables = {'login': USER_NAME, 'cursor': cursor, 'owner_affiliation': config.LANGUAGE_AFFILIATIONS}
    repositories = simple_request(language_getter.__name__, query, variables).json()['data']['user']['repositories']
    for node in repositories['nodes']:
        if node is None: continue # the token cannot read this repository
        repos.append((node['nameWithOwner'],
                      {edge['node']['name']: edge['size'] for edge in node['languages']['edges']}))
    if repositories['pageInfo']['hasNextPage']:
        return language_getter(repositories['pageInfo']['endCursor'], repos)
    return repos


def my_commits_by_repo():
    """
    Reads {sha256(owner/name): commits authored by me} out of the LOC cache.

    GitHub reports a repository's language bytes in full - it has no notion of
    whose bytes they are. Counting every organisation repo therefore credits me
    with my teammates' languages. The cache already knows how many commits in
    each repo are mine, so it is the one source available for telling the two
    apart. Empty until loc_query() has run.
    """
    try:
        with open(cache_filename()) as f:
            lines = f.readlines()[config.CACHE_COMMENT_SIZE:]
    except FileNotFoundError:
        return {}
    counts = {}
    for line in lines:
        fields = line.split()
        if len(fields) >= 3:
            counts[fields[0]] = int(fields[2])
    return counts


def fit(items, separator, budget):
    """
    Joins as many items as fit in `budget` columns. Language names vary in
    length, so a fixed count would sometimes run off the edge of the card and
    sometimes leave it looking sparse; this drops the tail instead.
    """
    kept = []
    for item in items:
        if kept and len(separator.join(kept + [item])) > budget:
            break
        kept.append(item)
    return separator.join(kept)


WAKATIME_API = 'https://wakatime.com/api/v1'


def wakatime_stats():
    """
    Total hours coded, from WakaTime's public stats endpoint.

    No API key: the endpoint is public for whichever range the account
    publishes, and this one publishes `all_time`. Returns '' on any failure, so
    a WakaTime outage costs the row and nothing else.

    WakaTime answers 202 while it is recomputing and still hands back the last
    figures, so that counts as success alongside 200.
    """
    if not config.WAKATIME_USER:
        return ''
    url = '{}/users/{}/stats/{}'.format(WAKATIME_API, config.WAKATIME_USER,
                                        config.WAKATIME_RANGE)
    try:
        response = requests.get(url, timeout=30)
    except requests.exceptions.RequestException as error:
        print('   wakatime: {}'.format(error))
        return ''
    if response.status_code not in (200, 202):
        print('   wakatime: {} returned {}'.format(config.WAKATIME_RANGE, response.status_code))
        return ''
    data = response.json().get('data') or {}
    total = data.get('human_readable_total')
    average = data.get('human_readable_daily_average')
    if not total:
        return ''
    # 'hrs'/'mins' rather than WakaTime's spelling keeps the row inside budget
    total = total.replace(' hrs', 'h').replace(' hr', 'h').replace(' mins', 'm').replace(' min', 'm')
    if average:
        average = average.replace(' hrs', 'h').replace(' hr', 'h').replace(' mins', 'm').replace(' min', 'm')
        return '{} total · {}/day'.format(total, average)
    return '{} total'.format(total)


SPOTIFY_TOKEN_URL = 'https://accounts.spotify.com/api/token'
SPOTIFY_API = 'https://api.spotify.com/v1'


def spotify_access_token():
    """
    Trades the long-lived refresh token for a short-lived access token.

    Returns None when Spotify is not configured, which is the normal case for
    a fresh fork - the music block is optional and its absence must never fail
    a build.
    """
    client_id = os.environ.get('SPOTIFY_CLIENT_ID')
    client_secret = os.environ.get('SPOTIFY_CLIENT_SECRET')
    refresh_token = os.environ.get('SPOTIFY_REFRESH_TOKEN')
    if not (client_id and client_secret and refresh_token):
        return None
    try:
        response = requests.post(
            SPOTIFY_TOKEN_URL, timeout=30,
            data={'grant_type': 'refresh_token', 'refresh_token': refresh_token},
            auth=(client_id, client_secret))
    except requests.exceptions.RequestException as error:
        print('   spotify: {} - skipping the music block'.format(error))
        return None
    if response.status_code != 200:
        print('   spotify: token refresh returned {} - skipping the music block'.format(response.status_code))
        return None
    return response.json().get('access_token')


def spotify_top(access_token, kind, time_range, limit=20):
    """`kind` is 'artists' or 'tracks'. Returns [] on any failure."""
    try:
        response = requests.get(
            '{}/me/top/{}'.format(SPOTIFY_API, kind), timeout=30,
            headers={'Authorization': 'Bearer ' + access_token},
            params={'time_range': time_range, 'limit': limit})
    except requests.exceptions.RequestException as error:
        print('   spotify: {}'.format(error))
        return []
    if response.status_code != 200:
        print('   spotify: /me/top/{} returned {}'.format(kind, response.status_code))
        return []
    return response.json().get('items', [])


def music_stats():
    """
    The Music block's three rows, or {} when Spotify is not configured.

    Uses top artists/tracks rather than the currently-playing endpoint on
    purpose: this card is regenerated once a day, so "now playing" could only
    ever report whatever happened to be on at 05:30 UTC. Top items over a
    rolling window change slowly enough that a daily rebuild tells the truth.
    """
    token = spotify_access_token()
    if not token:
        return {}
    artists = spotify_top(token, 'artists', config.MUSIC_TIME_RANGE)
    tracks = spotify_top(token, 'tracks', config.MUSIC_TIME_RANGE)
    if not artists and not tracks:
        return {}

    stats = {}
    if tracks:
        # 'On repeat' lists the tracks themselves; 'Top track' below names the
        # single top one with its artist, so start this list at the second to
        # avoid printing the same title twice.
        stats['tracks'] = fit_lines([strip_credits(t['name']) for t in tracks[1:]], ', ',
                                    render.value_budget('On repeat', config.MUSIC_COLS),
                                    config.MUSIC_TRACK_LINES)
        top = tracks[0]
        title = '{} - {}'.format(top['name'],
                                 ', '.join(a['name'] for a in top.get('artists', []))[:40])
        budget = render.value_budget('Top track', config.MUSIC_COLS)
        stats['track'] = title if len(title) <= budget else title[:budget - 1].rstrip() + '…'
    if artists:
        stats['artists'] = fit([a['name'] for a in artists], ', ',
                               render.value_budget('Top artists', config.MUSIC_COLS))
    return stats


def branch_commits(name_with_owner):
    """
    Commits I authored on the busiest branch of a repository.

    recursive_loc() only ever walks defaultBranchRef, which tells the whole
    story for most repos but reports a flat zero for one where my work sits on
    feature branches that were never merged into the default. That is not
    hypothetical: stardelite/BurseApp has 57 of my commits on one branch and
    none at all on its default, so the language filter would have thrown the
    repo - and every line of Vue in it - away.

    Returns the maximum across branches rather than the sum: branches share
    ancestors, so adding them up would count the same commit many times over.
    A lower bound is enough to answer "did I meaningfully work here?".
    """
    query_count('branch_commits')
    owner, repo = name_with_owner.split('/')
    query = '''
    query ($owner: String!, $repo: String!, $author: ID!) {
        repository(owner: $owner, name: $repo) {
            refs(refPrefix: "refs/heads/", first: 50) {
                nodes {
                    target {
                        ... on Commit {
                            history(author: {id: $author}) {
                                totalCount
                            }
                        }
                    }
                }
            }
        }
    }'''
    variables = {'owner': owner, 'repo': repo, 'author': OWNER_ID['id']}
    response = post_graphql(query, variables)
    if response.status_code != 200:
        return 0
    repository = (response.json().get('data') or {}).get('repository')
    if not repository:
        return 0
    return max((node['target']['history']['totalCount']
                for node in repository['refs']['nodes']
                if node.get('target', {}).get('history')), default=0)


# '(feat. X)', '(with X)', '[ft. X]' - and the en/em dash forms some labels use
CREDIT = re.compile(r'\s*[\(\[](?:feat\.?|ft\.?|with)\b[^)\]]*[\)\]]|\s+[-–—]\s+(?:feat\.?|ft\.?|with)\b.*$',
                    re.IGNORECASE)


def strip_credits(title):
    """
    'Cry (with Black Sherif)' -> 'Cry'.

    Featured-artist credits cost 15-20 of the 35 columns this row has, and the
    guests already appear in the Top artists row below, so the information is
    not lost - only the repetition.
    """
    return CREDIT.sub('', title).strip() or title


def fit_lines(items, separator, budget, max_lines=1):
    """
    Like fit(), but spills into up to `max_lines` lines of `budget` columns.

    The music column is only 35 columns wide, and track titles are long, so a
    single line often held just two of them. Non-final lines get a trailing
    separator added by the renderer, hence the one column held back.
    """
    room = budget - 1 if max_lines > 1 else budget
    lines, current = [], []
    for item in items:
        if current and len(separator.join(current + [item])) > room:
            lines.append(separator.join(current))
            if len(lines) >= max_lines:
                return lines
            current = [item]
        else:
            current.append(item)
    if current:
        lines.append(separator.join(current))
    return lines[:max_lines]


def language_stats(repos):
    """
    Turns per-repository byte counts into the two language rows on the card: a
    plain list of names, and a percentage breakdown.

    Two filters run first. LANGUAGE_IGNORE drops markup and config languages
    that would otherwise crowd out what is actually being written, and
    LANGUAGE_MIN_COMMITS drops repositories I barely touched - without it a
    teammate's Laravel backend that I opened two pull requests against reports
    as 12% of "my" languages.
    """
    mine = my_commits_by_repo()
    totals = {}
    for name, languages in repos:
        if mine:
            count = mine.get(hashlib.sha256(name.encode('utf-8')).hexdigest(), 0)
            if count < config.LANGUAGE_MIN_COMMITS:
                # the cache only knows the default branch; look wider before
                # writing the repo off
                count = branch_commits(name)
            if count < config.LANGUAGE_MIN_COMMITS:
                continue
        for language, size in languages.items():
            totals[language] = totals.get(language, 0) + size
    counted = {name: size for name, size in totals.items() if name not in config.LANGUAGE_IGNORE}
    if not counted:
        return 'n/a', 'n/a'
    total = sum(counted.values())
    ranked = sorted(counted.items(), key=lambda item: -item[1])[:config.LANGUAGE_COUNT]
    names = fit([name for name, _ in ranked], ', ',
                render.value_budget('Languages.Programming'))
    bar = fit(['{} {:.0f}%'.format(name, 100 * size / total) for name, size in ranked],
              ' · ', render.value_budget('Top Languages'))
    return names, bar


SPARK_LEVELS = '▁▂▃▄▅▆▇█'


def contribution_graph():
    """
    Uses GitHub's GraphQL API to fetch the contribution calendar for the
    last year, collapsed to one bar per week. This is the same data behind the
    green squares on a profile page, drawn as a sparkline under the portrait.
    """
    query_count('contribution_graph')
    query = '''
    query($login: String!) {
        user(login: $login) {
            contributionsCollection {
                contributionCalendar {
                    totalContributions
                    weeks {
                        contributionDays {
                            contributionCount
                        }
                    }
                }
            }
        }
    }'''
    calendar = simple_request(contribution_graph.__name__, query, {'login': USER_NAME}) \
        .json()['data']['user']['contributionsCollection']['contributionCalendar']
    weekly = [sum(day['contributionCount'] for day in week['contributionDays'])
              for week in calendar['weeks']]
    return weekly, calendar['totalContributions']


def sparkline(weekly, width):
    """
    Renders weekly totals as block characters. Scaled against the busiest week
    rather than an absolute number, so the shape stays readable whether the
    peak is 5 commits or 500.

    The square root is what makes it legible: contribution weeks are heavily
    skewed - one sprint week can be twenty times a normal one - and on a linear
    scale that single spike flattens every other week onto the bottom bar.
    """
    weekly = weekly[-width:]
    peak = max(weekly) if weekly else 0
    if not peak:
        return SPARK_LEVELS[0] * len(weekly), 0
    top = len(SPARK_LEVELS) - 1
    return ''.join(SPARK_LEVELS[min(top, round(top * (value / peak) ** 0.5))]
                   for value in weekly), peak


def recursive_loc(owner, repo_name, data, cache_comment, addition_total=0, deletion_total=0, my_commits=0, cursor=None):
    """
    Uses GitHub's GraphQL API and cursor pagination to fetch 100 commits from a repository at a time
    """
    query_count('recursive_loc')
    query = '''
    query ($repo_name: String!, $owner: String!, $cursor: String) {
        repository(name: $repo_name, owner: $owner) {
            defaultBranchRef {
                target {
                    ... on Commit {
                        history(first: 100, after: $cursor) {
                            totalCount
                            edges {
                                node {
                                    ... on Commit {
                                        committedDate
                                    }
                                    author {
                                        user {
                                            id
                                        }
                                    }
                                    deletions
                                    additions
                                }
                            }
                            pageInfo {
                                endCursor
                                hasNextPage
                            }
                        }
                    }
                }
            }
        }
    }'''
    variables = {'repo_name': repo_name, 'owner': owner, 'cursor': cursor}
    request = post_graphql(query, variables) # I cannot use simple_request(), because I want to save the file before raising Exception
    if request.status_code == 200:
        if request.json()['data']['repository']['defaultBranchRef'] != None: # Only count commits if repo isn't empty
            return loc_counter_one_repo(owner, repo_name, data, cache_comment, request.json()['data']['repository']['defaultBranchRef']['target']['history'], addition_total, deletion_total, my_commits)
        else: return (0, 0, 0) # empty repo - same shape as a real result, so callers can always unpack
    force_close_file(data, cache_comment) # saves what is currently in the file before this program crashes
    if request.status_code == 403:
        raise Exception('Too many requests in a short amount of time!\nYou\'ve hit the non-documented anti-abuse limit!')
    raise Exception('recursive_loc() has failed with a', request.status_code, request.text, QUERY_COUNT)


def loc_counter_one_repo(owner, repo_name, data, cache_comment, history, addition_total, deletion_total, my_commits):
    """
    Recursively call recursive_loc (since GraphQL can only search 100 commits at a time)
    only adds the LOC value of commits authored by me
    """
    for node in history['edges']:
        if node['node']['author']['user'] == OWNER_ID:
            my_commits += 1
            addition_total += node['node']['additions']
            deletion_total += node['node']['deletions']

    if history['edges'] == [] or not history['pageInfo']['hasNextPage']:
        return addition_total, deletion_total, my_commits
    else: return recursive_loc(owner, repo_name, data, cache_comment, addition_total, deletion_total, my_commits, history['pageInfo']['endCursor'])


def loc_query(owner_affiliation, comment_size=0, force_cache=False, cursor=None, edges=None):
    """
    Uses GitHub's GraphQL API to query all the repositories I have access to (with respect to owner_affiliation)
    Queries 60 repos at a time, because larger queries give a 502 timeout error and smaller queries send too many
    requests and also give a 502 error.
    Returns the total number of lines of code in all repositories
    """
    query_count('loc_query')
    edges = [] if edges is None else edges # a shared [] default would leak between calls
    query = '''
    query ($owner_affiliation: [RepositoryAffiliation], $login: String!, $cursor: String) {
        user(login: $login) {
            repositories(first: 60, after: $cursor, ownerAffiliations: $owner_affiliation) {
            edges {
                node {
                    ... on Repository {
                        nameWithOwner
                        defaultBranchRef {
                            target {
                                ... on Commit {
                                    history {
                                        totalCount
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
                pageInfo {
                    endCursor
                    hasNextPage
                }
            }
        }
    }'''
    variables = {'owner_affiliation': owner_affiliation, 'login': USER_NAME, 'cursor': cursor}
    repositories = simple_request(loc_query.__name__, query, variables).json()['data']['user']['repositories']
    if repositories['pageInfo']['hasNextPage']:   # If repository data has another page
        return loc_query(owner_affiliation, comment_size, force_cache, repositories['pageInfo']['endCursor'], edges + repositories['edges'])
    return cache_builder(edges + repositories['edges'], comment_size, force_cache)


CACHE_HEADER = [
    'Line-of-code cache for {user}. Generated by today.py - do not hand-edit.',
    '',
    'One line per repository:',
    '    <sha256 of owner/name> <commits in repo> <my commits> <added> <deleted>',
    'A repository is only re-walked when its commit count changes, which is what',
    'keeps a daily build to seconds instead of several hundred API calls.',
    'Delete this file (or run the workflow with force_cache) to rebuild it.',
]


def cache_filename():
    """
    The cache file is keyed by username, so switching accounts starts a clean
    cache instead of silently reusing someone else's numbers.
    """
    return 'cache/' + hashlib.sha256(USER_NAME.encode('utf-8')).hexdigest() + '.txt'


def write_cache(filename, cache_comment, data):
    with open(filename, 'w') as f:
        f.writelines(cache_comment)
        f.writelines(data)


def cache_builder(edges, comment_size, force_cache, loc_add=0, loc_del=0):
    """
    Checks each repository in edges to see if it has been updated since the last time it was cached
    If it has, run recursive_loc on that repository to update the LOC count
    """
    edges = [edge for edge in edges if edge['node'] is not None] # drop repositories the token cannot read
    cached = True # Assume all repositories are cached
    filename = cache_filename()
    try:
        with open(filename, 'r') as f:
            data = f.readlines()
    except FileNotFoundError: # If the cache file doesn't exist, create it
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        header = [line.format(user=USER_NAME) + '\n' for line in CACHE_HEADER]
        # the reader skips exactly comment_size lines, so pad or trim to match
        data = (header + ['\n'] * comment_size)[:comment_size]
        with open(filename, 'w') as f:
            f.writelines(data)

    if len(data)-comment_size != len(edges) or force_cache: # If the number of repos has changed, or force_cache is True
        cached = False
        flush_cache(edges, filename, comment_size)
        with open(filename, 'r') as f:
            data = f.readlines()

    cache_comment = data[:comment_size] # save the comment block
    data = data[comment_size:] # remove those lines
    for index in range(len(edges)):
        repo_hash, commit_count, *__ = data[index].split()
        if repo_hash == hashlib.sha256(edges[index]['node']['nameWithOwner'].encode('utf-8')).hexdigest():
            dirty = True
            try:
                if int(commit_count) != edges[index]['node']['defaultBranchRef']['target']['history']['totalCount']:
                    # if commit count has changed, update loc for that repo
                    owner, repo_name = edges[index]['node']['nameWithOwner'].split('/')
                    print('   walking', edges[index]['node']['nameWithOwner'])
                    loc = recursive_loc(owner, repo_name, data, cache_comment)
                    data[index] = repo_hash + ' ' + str(edges[index]['node']['defaultBranchRef']['target']['history']['totalCount']) + ' ' + str(loc[2]) + ' ' + str(loc[0]) + ' ' + str(loc[1]) + '\n'
                else:
                    dirty = False
            except TypeError: # If the repo is empty
                data[index] = repo_hash + ' 0 0 0 0\n'
            if dirty:
                # Persist after every repository rather than once at the end. A
                # cold build walks every commit in every repo and can run for
                # half an hour; if it is interrupted - a CI timeout, a rate
                # limit - the next run picks up where this one stopped instead
                # of starting over.
                write_cache(filename, cache_comment, data)
    write_cache(filename, cache_comment, data)
    for line in data:
        loc = line.split()
        loc_add += int(loc[3])
        loc_del += int(loc[4])
    return [loc_add, loc_del, loc_add - loc_del, cached]


def flush_cache(edges, filename, comment_size):
    """
    Wipes the cache file
    This is called when the number of repositories changes or when the file is first created
    """
    with open(filename, 'r') as f:
        data = []
        if comment_size > 0:
            data = f.readlines()[:comment_size] # only save the comment
    with open(filename, 'w') as f:
        f.writelines(data)
        for node in edges:
            f.write(hashlib.sha256(node['node']['nameWithOwner'].encode('utf-8')).hexdigest() + ' 0 0 0 0\n')


def add_archive():
    """
    Repositories I contributed to that have since been deleted, added back from
    their last known data. Optional - returns zeroes when the archive is absent,
    which is the normal case for a fresh fork.
    """
    empty = [0, 0, 0, 0, 0]
    try:
        with open('cache/repository_archive.txt', 'r') as f:
            data = f.readlines()
    except FileNotFoundError:
        return empty
    old_data = data
    data = data[7:len(data)-3] # remove the comment block
    if not data:
        return empty
    added_loc, deleted_loc, added_commits = 0, 0, 0
    contributed_repos = len(data)
    for line in data:
        repo_hash, total_commits, my_commits, *loc = line.split()
        added_loc += int(loc[0])
        deleted_loc += int(loc[1])
        if (my_commits.isdigit()): added_commits += int(my_commits)
    added_commits += int(old_data[-1].split()[4][:-1])
    return [added_loc, deleted_loc, added_loc - deleted_loc, added_commits, contributed_repos]


def force_close_file(data, cache_comment):
    """
    Forces the file to close, preserving whatever data was written to it
    This is needed because if this function is called, the program would've crashed before the file is properly saved and closed
    """
    filename = cache_filename()
    write_cache(filename, cache_comment, data)
    print('There was an error while writing to the cache file. The file,', filename, 'has had the partial data saved and closed.')


def stars_counter(data):
    """
    Count total stars in repositories owned by me
    """
    total_stars = 0
    for node in data:
        if node['node'] is None: continue # the token cannot read this repository
        total_stars += node['node']['stargazers']['totalCount']
    return total_stars


def commit_counter(comment_size):
    """
    Counts up my total commits, using the cache file created by cache_builder.
    """
    total_commits = 0
    with open(cache_filename(), 'r') as f:
        data = f.readlines()[comment_size:] # skip the comment block
    for line in data:
        total_commits += int(line.split()[2])
    return total_commits


def user_getter(username):
    """
    Returns the account ID and creation time of the user
    """
    query_count('user_getter')
    query = '''
    query($login: String!){
        user(login: $login) {
            id
            createdAt
        }
    }'''
    variables = {'login': username}
    request = simple_request(user_getter.__name__, query, variables)
    return {'id': request.json()['data']['user']['id']}, request.json()['data']['user']['createdAt']


def follower_getter(username):
    """
    Returns the number of followers of the user
    """
    query_count('follower_getter')
    query = '''
    query($login: String!){
        user(login: $login) {
            followers {
                totalCount
            }
        }
    }'''
    request = simple_request(follower_getter.__name__, query, {'login': username})
    return int(request.json()['data']['user']['followers']['totalCount'])


def uptime_start(acc_date):
    """
    Resolves config.UPTIME_FROM into the datetime the Uptime row counts from.
    """
    if config.UPTIME_FROM == 'account':
        return datetime.datetime.strptime(acc_date, '%Y-%m-%dT%H:%M:%SZ')
    return datetime.datetime.strptime(config.UPTIME_FROM, '%Y-%m-%d')


def query_count(funct_id):
    """
    Counts how many times the GitHub GraphQL API is called
    """
    QUERY_COUNT[funct_id] += 1


def perf_counter(funct, *args):
    """
    Calculates the time it takes for a function to run
    Returns the function result and the time differential
    """
    start = time.perf_counter()
    funct_return = funct(*args)
    return funct_return, time.perf_counter() - start


def formatter(query_type, difference, funct_return=False, whitespace=0):
    """
    Prints a formatted time differential
    Returns formatted result if whitespace is specified, otherwise returns raw result
    """
    print('{:<23}'.format('   ' + query_type + ':'), sep='', end='')
    print('{:>12}'.format('%.4f' % difference + ' s ')) if difference > 1 else print('{:>12}'.format('%.4f' % (difference * 1000) + ' ms'))
    if whitespace:
        return f"{'{:,}'.format(funct_return): <{whitespace}}"
    return funct_return


def main():
    global OWNER_ID
    print('Calculation times:')
    # user_getter returns e.g. ({'id': 'MDQ6VXNlcjk5MDgwODYz'}, '2022-02-05T13:23:42Z')
    user_data, user_time = perf_counter(user_getter, USER_NAME)
    OWNER_ID, acc_date = user_data
    formatter('account data', user_time)

    age_data, age_time = perf_counter(daily_readme, uptime_start(acc_date))
    formatter('age calculation', age_time)

    force_cache = os.environ.get('FORCE_CACHE', '').lower() in ('1', 'true', 'yes')
    total_loc, loc_time = perf_counter(loc_query, config.CONTRIB_AFFILIATIONS, config.CACHE_COMMENT_SIZE, force_cache)
    formatter('LOC (cached)', loc_time) if total_loc[-1] else formatter('LOC (no cache)', loc_time)

    commit_data, commit_time = perf_counter(commit_counter, config.CACHE_COMMENT_SIZE)
    formatter('commit counter', commit_time)
    star_data, star_time = perf_counter(graph_repos_stars, 'stars', config.OWNED_AFFILIATIONS)
    formatter('star counter', star_time)
    repo_data, repo_time = perf_counter(graph_repos_stars, 'repos', config.OWNED_AFFILIATIONS)
    formatter('my repositories', repo_time)
    contrib_data, contrib_time = perf_counter(graph_repos_stars, 'repos', config.CONTRIB_AFFILIATIONS)
    formatter('contributed repos', contrib_time)
    follower_data, follower_time = perf_counter(follower_getter, USER_NAME)
    formatter('follower counter', follower_time)
    # runs after loc_query, which is what populates the per-repo commit counts
    # language_stats() filters on
    language_repos, language_time = perf_counter(language_getter)
    formatter('languages', language_time)
    (weekly, year_total), contrib_graph_time = perf_counter(contribution_graph)
    formatter('contribution graph', contrib_graph_time)
    waka, waka_time = perf_counter(wakatime_stats)
    formatter('wakatime' if waka else 'wakatime (skipped)', waka_time)
    music, music_time = perf_counter(music_stats)
    formatter('spotify' if music else 'spotify (skipped)', music_time)

    language_names, language_bar = language_stats(language_repos)
    spark, peak = sparkline(weekly, config.SPARK_WEEKS)
    comma = '{:,}'.format
    data = {
        'age': age_data,
        'repos': comma(repo_data),
        'contrib': comma(contrib_data),
        'stars': comma(star_data),
        'commits': comma(commit_data),
        'followers': comma(follower_data),
        'loc_add': comma(total_loc[0]),
        'loc_del': comma(total_loc[1]),
        'loc_net': comma(total_loc[2]),
        'language_names': language_names,
        'language_bar': language_bar,
        'spark': spark,
        'spark_caption': '{} contributions in the last year · peak {}/week'.format(
            comma(year_total), comma(peak)),
        'music': music,
        'wakatime': waka,
    }

    written = render.render_all(data)
    print('\nWrote:', ', '.join(written))
    print('Total GitHub GraphQL API calls:', '{:>3}'.format(sum(QUERY_COUNT.values())))
    for funct_name, count in QUERY_COUNT.items():
        print('{:<28}'.format('   ' + funct_name + ':'), '{:>6}'.format(count))


if __name__ == '__main__':
    main()
