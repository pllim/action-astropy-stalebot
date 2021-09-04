import json
import os
import sys
import time

import dateutil.parser
from github import Github
from humanize import naturaldelta

# This workflow only makes sense in these events.
event_name = os.environ.get('GITHUB_EVENT_NAME', 'unknown')
if event_name not in ('schedule', 'workflow_dispatch'):
    print(f'No-op for {event_name}')
    sys.exit(0)

event_jsonfile = os.environ.get('GITHUB_EVENT_PATH', None)
if event_jsonfile:
    with open(event_jsonfile, encoding='utf-8') as fin:
        event = json.load(fin)
else:
    # Dummy values for testing only!
    event = {'repository': {'full_name': 'astropy/astropy'}}

if event_name == 'schedule':
    reponame = os.environ['GITHUB_REPOSITORY']
else:
    reponame = event['repository']['full_name']

is_dryrun = int(os.environ.get('STALEBOT_DRYRUN', '0')) == 1
stale_label = os.environ.get('STALEBOT_STALE_LABEL', 'Close?')
keep_open_label = os.environ.get('STALEBOT_KEEP_OPEN_LABEL', 'keep-open')
closed_by_bot_label = os.environ.get('STALEBOT_CLOSED_BY_BOT_LABEL', 'closed-by-bot')
max_prs = int(os.environ.get('STALEBOT_MAX_PRS', '200'))
sleep = float(os.environ.get('STALEBOT_SLEEP', '0'))

# Warn after 5 months.
warn_seconds = float(os.environ.get('STALEBOT_WARN_PR_SECONDS', '12960000'))

# Close after 1 month.
close_seconds = float(os.environ.get('STALEBOT_CLOSE_PR_SECONDS', '2592000'))


# Copied over from baldrick
def unwrap(text):
    """Given text that has been wrapped, unwrap it but preserve paragraph breaks."""

    # Split into lines and get rid of newlines and leading/trailing spaces
    lines = [line.strip() for line in text.splitlines()]

    # Join back with predictable newline character
    text = os.linesep.join(lines)

    # Replace cases where there are more than two successive line breaks
    while 3 * os.linesep in text:
        text = text.replace(3 * os.linesep, 2 * os.linesep)

    # Split based on multiple newlines
    paragraphs = text.split(2 * os.linesep)

    # Join each paragraph using spaces instead of newlines
    paragraphs = [paragraph.replace(os.linesep, ' ') for paragraph in paragraphs]

    # Join paragraphs together
    return (2 * os.linesep).join(paragraphs)


PULL_REQUESTS_CLOSE_WARNING = unwrap("""
Hi humans :wave: - this pull request hasn't had any new commits for
approximately {pasttime}. **I plan to close this in {futuretime} if the pull
request doesn't have any new commits by then.**

In lieu of a stalled pull request, please consider closing this and open an
issue instead if a reminder is needed to revisit in the future. Maintainers
may also choose to add **{keepopen}** label to keep this PR open but it is
discouraged unless absolutely necessary.

If this PR still needs to be reviewed, as an author, you can rebase it
to reset the clock.

*If you believe I commented on this pull request incorrectly, please report
this [here](https://github.com/pllim/action-astropy-stalebot/issues).*
""")


# NOTE: This must be in-sync with PULL_REQUESTS_CLOSE_WARNING
def is_close_warning(message):
    return 'Hi humans :wave: - this pull request hasn\'t had any new commits' in message


PULL_REQUESTS_CLOSE_EPILOGUE = unwrap("""
I'm going to close this pull request as per my previous message. If you think
what is being added/fixed here is still important, please remember to open an
issue to keep track of it. Thanks!

*If this is the first time I am commenting on this issue, or if you believe
I closed this issue incorrectly, please report this
[here](https://github.com/pllim/action-astropy-stalebot/issues).*
""")


# NOTE: This must be in-sync with PULL_REQUESTS_CLOSE_EPILOGUE
def is_close_epilogue(message):
    return "I'm going to close this pull request" in message


def process_one_pr(pr, now, warn_seconds, close_seconds,
                   stale_label='Close?', keep_open_label='keep-open',
                   closed_by_bot_label='closed-by-bot', is_dryrun=False):
    """Check the given PR and close it if needed.

    Parameters
    ----------
    pr : obj
        PyGithub PullRequest instance of the PR to be checked.

    now : float
        Time now in seconds.

    *args, **kwargs
        See :func:`process_prs`.

    """
    all_pr_labels = [lbl.name for lbl in pr.labels]
    print(f'Checking {pr.number} with labels {all_pr_labels}')

    if keep_open_label in all_pr_labels:
        print(f'-> PROTECTED by {keep_open_label}, skipping and '
              f'removing "{stale_label}" label if it exists')
        if not is_dryrun and stale_label in all_pr_labels:
            pr.remove_from_labels(stale_label)
        return

    issue = pr.as_issue()  # Some API only available for Issue

    # Find last commit timestamp.
    last_committed = None
    last_committed_sec = 0
    for commit in pr.get_commits():
        cur_commit_time = dateutil.parser.parse(commit.raw_data['commit']['committer']['date'])
        cur_commit_time_sec = cur_commit_time.timestamp()
        if cur_commit_time_sec > last_committed_sec:
            last_committed = cur_commit_time
            last_committed_sec = cur_commit_time_sec

    if last_committed is None:
        print(f'-> LAST COMMIT NOT FOUND, need to debug')
        return

    time_since_last_commit = now - last_committed_sec

    # Grab timestamp of warning if it exists.
    time_since_last_warning = -1
    last_warn_time = None
    last_warn_time_sec = 0
    for comment in pr.get_issue_comments():
        if (comment.user.login not in ('github-actions[bot]', 'astropy-bot[bot]', 'pllim') or
                not is_close_warning(comment.body)):
            continue
        cur_labeled_time = dateutil.parser.parse(comment.raw_data['created_at'])
        cur_labeled_time_sec = cur_labeled_time.timestamp()
        if cur_labeled_time_sec > last_warn_time_sec:
            last_warn_time = cur_labeled_time
            last_warn_time_sec = cur_labeled_time_sec
    if last_warn_time_sec > 0:
        time_since_last_warning = now - last_warn_time_sec

    # We check for staleness and handle that first. This can be from bot or human.
    if stale_label in all_pr_labels:
        # Find when the label was added. Only count the most recent event.
        last_labeled = None
        labeled_time_sec = 0
        for timeline in issue.get_timeline():
            if timeline.event != 'labeled' or timeline.raw_data['label']['name'] != stale_label:
                continue
            cur_created_at = dateutil.parser.parse(timeline.raw_data['created_at'])
            cur_labeled_time_sec = cur_created_at.timestamp()
            if cur_labeled_time_sec > labeled_time_sec:
                last_labeled = cur_created_at
                labeled_time_sec = cur_labeled_time_sec

        if last_labeled is None:
            print(f'-> {stale_label} exists but cannot find when it was added, need to debug')
            return

        # Note: If warning time is before label time, it's as if the warning
        # did not exist since it's no longer relevant.
        if last_warn_time_sec >= labeled_time_sec:
            if time_since_last_warning > close_seconds:
                print(f'-> CLOSING PR {pr.number}, {naturaldelta(time_since_last_warning)} '
                      'since last warning')
                if not is_dryrun:
                    pr.add_to_labels(closed_by_bot_label)
                    issue.create_comment(PULL_REQUESTS_CLOSE_EPILOGUE)
                    pr.edit(state='closed')
            else:
                print(f'-> OK PR {pr.number} (already warned), '
                      f'labeled on {last_labeled}, '
                      f'warned on {last_warn_time}')
        else:  # Need to warn first
            if time_since_last_warning < 0:
                print(f'-> WARNING PR {pr.number}, labeled on {last_labeled}, '
                      'no warning ever issued')
            else:
                print(f'-> WARNING PR {pr.number}, labeled on {last_labeled}, '
                      f'warning issued on {last_warn_time} no longer applicable')
            if not is_dryrun:
                issue.create_comment(PULL_REQUESTS_CLOSE_WARNING.format(
                    keepopen=keep_open_label,
                    pasttime=naturaldelta(time_since_last_commit),
                    futuretime=naturaldelta(close_seconds)))

    # The PR is not yet marked as stale. Mark it as stale as appropriate.
    else:
        if time_since_last_commit > warn_seconds:
            print(f'-> MARK PR {pr.number} as stale with "{stale_label}" label, '
                  f'last commit was {last_committed}')
            if not is_dryrun:
                pr.add_to_labels(stale_label)
            # Warn if no warning exists or last warning made before last commit.
            if last_warn_time_sec < last_committed_sec:
                if time_since_last_warning < 0:
                    print(f'-> WARNING PR {pr.number}, no warning ever issued')
                else:
                    print(f'-> WARNING PR {pr.number}, '
                          f'warning issued on {last_warn_time} no longer applicable')
                if not is_dryrun:
                    issue.create_comment(PULL_REQUESTS_CLOSE_WARNING.format(
                        keepopen=keep_open_label,
                        pasttime=naturaldelta(time_since_last_commit),
                        futuretime=naturaldelta(close_seconds)))
            else:
                print(f'-> OK PR {pr.number} (already warned), '
                      f'{naturaldelta(time_since_last_warning)} since last warning')
        else:
            print(f'-> OK PR {pr.number} (not stale), last commit was {last_committed}')


def process_pull_requests(repository, warn_seconds, close_seconds,
                          stale_label='Close?', keep_open_label='keep-open',
                          closed_by_bot_label='closed-by-bot', max_prs=200,
                          sleep=0, is_dryrun=False):
    """Check for stale PRs and close them if needed.

    Parameters
    ----------
    repository : str
        The repository in which to check for stale PRs
        in the format of ``org/repo`` or ``user/repo``.

    warn_seconds : float
        After how many seconds to warn about stale PRs after
        the last commit?

    close_seconds : float
        After how many seconds to close stale PRs after last warning?

    stale_label : str
        Label to mark PR as stale. This is usually applied automatically
        by bot or manually by a maintainer.

    keep_open_label : str
        Label to skip this check. This is applied manually by a maintainer.
        If both this and ``stale_label`` are found, ``stale_label`` will be removed.

    closed_by_bot_label : str
        Label the bot will apply when closing a stale PR.

    max_prs : int
        Maximum number of PRs to process. This is skipped if set to a negative number.

    sleep : float
        Number of seconds to sleep between PRs. Ignored for dry-run.

    is_dryrun : bool
        Set to `True` for dry-run only.

    """
    i = 0
    now = time.time()
    g = Github(os.environ.get('GITHUB_TOKEN'))
    repo = g.get_repo(repository)

    for pr in repo.get_pulls(state='open'):
        if max_prs >= 0 and i >= max_prs:
            break
        try:
            process_one_pr(pr, now, warn_seconds, close_seconds,
                           stale_label=stale_label, keep_open_label=keep_open_label,
                           closed_by_bot_label=closed_by_bot_label, is_dryrun=is_dryrun)
        except Exception as e:
            print(f'-> ERROR: {repr(e)}')
        i += 1
        if not is_dryrun and sleep > 0:
            time.sleep(sleep)

    print('Finished checking for stale pull requests')


process_pull_requests(reponame, warn_seconds, close_seconds,
                      stale_label=stale_label, keep_open_label=keep_open_label,
                      closed_by_bot_label=closed_by_bot_label, max_prs=max_prs,
                      sleep=sleep, is_dryrun=is_dryrun)
