import json
import os
import sys
import time

import dateutil.parser
from github import Github
from humanize import naturaltime, naturaldelta

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
max_issues = int(os.environ.get('STALEBOT_MAX_ISSUES', '50'))
sleep = float(os.environ.get('STALEBOT_SLEEP', '0'))

# Warn immediately.
warn_seconds = float(os.environ.get('STALEBOT_WARN_ISSUE_SECONDS', '0'))

# Close after a week.
close_seconds = float(os.environ.get('STALEBOT_CLOSE_ISSUE_SECONDS', '604800'))


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


ISSUE_CLOSE_WARNING = unwrap("""
Hi humans :wave: - this issue was labeled as **{closelabel}** approximately
{pasttime}. If you think this issue should not be closed, a maintainer should
remove the **{closelabel}** label - otherwise, I will close this issue in
{futuretime}.

*If you believe I commented on this issue incorrectly, please report this
[here](https://github.com/pllim/action-astropy-stalebot/issues)*
""")


# NOTE: This must be in-sync with ISSUE_CLOSE_WARNING
def is_close_warning(message):
    return f'Hi humans :wave: - this issue was labeled as **{stale_label}**' in message


ISSUE_CLOSE_EPILOGUE = unwrap("""
I'm going to close this issue as per my previous message, but if you feel that
this issue should stay open, then feel free to re-open and remove the
 **{closelabel}** label.

*If this is the first time I am commenting on this issue, or if you believe I
closed this issue incorrectly, please report this
[here](https://github.com/pllim/action-astropy-stalebot/issues)*
""")


# NOTE: This must be in-sync with ISSUE_CLOSE_EPILOGUE
def is_close_epilogue(message):
    return "I'm going to close this issue as per my previous message" in message


def process_one_issue(issue, now, warn_seconds, close_seconds,
                      stale_label='Close?', keep_open_label='keep-open',
                      closed_by_bot_label='closed-by-bot', is_dryrun=False):
    """Check the given issue and close it if needed. Pull request is skipped.

    Parameters
    ----------
    issue : obj
        PyGithub Issue instance of the issue to be checked.

    now : float
        Time now in seconds.

    *args, **kwargs
        See :func:`process_issues`.

    """
    if issue.pull_request is not None:
        print(f'Skipping {issue.number} because it is a pull request')
        return

    all_issue_labels = [lbl.name for lbl in issue.labels]

    if stale_label not in all_issue_labels:  # Nothing to do
        print(f'Skipping {issue.number}, {stale_label} not found in {all_issue_labels}')
        return

    if keep_open_label in all_issue_labels:
        print(f'Skipping {issue.number} due to "{keep_open_label}" label, '
              f'removing "{stale_label}" label')
        if not is_dryrun:
            issue.remove_from_labels(stale_label)
        return

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

    print(f'Checking Issue {issue.number} marked stale on {last_labeled} '
          f'with labels {all_issue_labels}')
    time_since_stale_label = now - labeled_time_sec

    # Note: If warning time is before label time, it's as if the warning
    # did not exist since it's no longer relevant.

    time_since_last_warning = -1
    last_warn_time_sec = 0

    for comment in issue.get_comments(since=last_labeled):
        if (comment.user.login not in ('github-actions[bot]', 'astropy-bot[bot]', 'pllim') or
                not is_close_warning(comment.body)):
            continue
        cur_labeled_time_sec = dateutil.parser.parse(comment.raw_data['created_at']).timestamp()
        if cur_labeled_time_sec > last_warn_time_sec:
            last_warn_time_sec = cur_labeled_time_sec

    if last_warn_time_sec > 0:
        time_since_last_warning = now - last_warn_time_sec

    # We only close issues if there has been a warning before, and
    # the time since the warning exceeds the threshold specified by
    # close_seconds.
    if time_since_last_warning > close_seconds:
        # Even if the bot closed this before, if we get to this point, this issue
        # deserves to be closed again with new comment. Maintainer should have used
        # keep_open_label if they do not want this to happen.
        print(f'-> CLOSING issue {issue.number}, {naturaldelta(time_since_last_warning)} '
              'since last warning')
        if not is_dryrun:
            issue.add_to_labels(closed_by_bot_label)
            issue.create_comment(ISSUE_CLOSE_EPILOGUE.format(closelabel=stale_label))
            issue.edit(state='closed')

    elif time_since_stale_label > warn_seconds:
        if time_since_last_warning < 0:
            print(f'-> WARNING issue {issue.number}, {naturaldelta(time_since_stale_label)} since stale')
            if not is_dryrun:
                issue.create_comment(ISSUE_CLOSE_WARNING.format(
                    closelabel=stale_label,
                    pasttime=naturaltime(time_since_stale_label),
                    futuretime=naturaldelta(close_seconds)))
        else:
            print(f'-> OK issue {issue.number} (already warned), '
                  f'{naturaldelta(time_since_stale_label)} since stale')

    else:
        print(f'-> OK issue {issue.number}, '
              f'{naturaldelta(time_since_last_warning)} since last warning, '
              f'{naturaldelta(time_since_stale_label)} since stale')


def process_issues(repository, warn_seconds, close_seconds,
                   stale_label='Close?', keep_open_label='keep-open',
                   closed_by_bot_label='closed-by-bot', max_issues=50,
                   sleep=0, is_dryrun=False):
    """Check for stale issues and close them if needed.

    Parameters
    ----------
    repository : str
        The repository in which to check for stale issues
        in the format of ``org/repo`` or ``user/repo``.

    warn_seconds : float
        After how many seconds to warn about stale issues after
        ``stale_label`` is applied?

    close_seconds : float
        After how many seconds to close stale issues after last warning?

    stale_label : str
        Label to mark issue as stale. This is applied manually by a maintainer.

    keep_open_label : str
        Label to skip this check. This is applied manually by a maintainer.
        If both this and ``stale_label`` are found, ``stale_label`` will be removed.

    closed_by_bot_label : str
        Label the bot will apply when closing a stale issue.

    max_issues : int
        Maximum number of issues to process. This is skipped if set to a negative number.

    sleep : float
        Number of seconds to sleep between issues. Ignored for dry-run.

    is_dryrun : bool
        Set to `True` for dry-run only.

    """
    i = 0
    now = time.time()
    g = Github(os.environ.get('GITHUB_TOKEN'))
    repo = g.get_repo(repository)

    # Get issues labeled as stale.
    for issue in repo.get_issues(state='open', labels=[stale_label]):
        if max_issues >= 0 and i >= max_issues:
            break
        process_one_issue(issue, now, warn_seconds, close_seconds,
                          stale_label=stale_label, keep_open_label=keep_open_label,
                          closed_by_bot_label=closed_by_bot_label, is_dryrun=is_dryrun)
        i += 1
        if not is_dryrun and sleep > 0:
            time.sleep(sleep)

    print('Finished processing stale issues')


process_issues(reponame, warn_seconds, close_seconds,
               stale_label=stale_label, keep_open_label=keep_open_label,
               closed_by_bot_label=closed_by_bot_label, max_issues=max_issues,
               sleep=sleep, is_dryrun=is_dryrun)
