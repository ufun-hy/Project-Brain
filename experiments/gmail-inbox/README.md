# Gmail Inbox Experiment v0

This is the first transport experiment for Project Brain.

It verifies only this path:

```text
ChatGPT Web Project -> Gmail -> local Python reader
```

It does **not**:

- modify Gmail messages
- mark messages as read
- write to a Git repository
- run shell commands
- invoke Codex
- create commits or pull requests

## Security boundary

The script uses Gmail's read-only OAuth scope and accepts messages only when:

1. the message is unread;
2. the subject starts with `[Project Brain]`;
3. the sender exactly matches `PB_ALLOWED_SENDER`.

The allowed sender must be set explicitly with `PB_ALLOWED_SENDER`.

Never commit `credentials.json` or `token.json`.

## 1. Google Cloud setup

1. Create or select a Google Cloud project.
2. Enable the Gmail API.
3. Configure the OAuth consent screen.
4. For a personal Gmail account, choose an external audience and add your own
   Gmail address as a test user.
5. Create an OAuth client with application type **Desktop app**.
6. Download the JSON credential.
7. Rename it to `credentials.json` and place it in the runtime config directory.

Expected location:

```text
~/.project-brain/config/credentials.json
```

## 2. Run

From the repository root:

```bash
cd experiments/gmail-inbox
chmod +x run.sh
PB_ALLOWED_SENDER="trusted-sender@example.com" ./run.sh
```

On the first run, a browser window opens for Google authorization. Choose the
configured account and approve read-only Gmail access.

The authorization token is stored locally as:

```text
~/.project-brain/config/token.json
```

## 3. Expected result

The terminal should print JSON resembling:

```json
{
  "mode": "read_only",
  "count": 1,
  "messages": [
    {
      "subject": "[Project Brain] Bridge connectivity test",
      "body": "type: connectivity_test\n..."
    }
  ]
}
```

A copy is saved under `~/.project-brain/results/` by `run.sh`.

## 4. Manual run without `run.sh`

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
export PB_ALLOWED_SENDER="trusted-sender@example.com"
python bridge.py --once --output ~/.project-brain/results/gmail-read-only-output.json
```

## 5. Troubleshooting

### `Missing credentials.json`

The downloaded OAuth desktop client file is not in the runtime config directory
or was not renamed correctly.

### `Access blocked` or test-user error

Open the Google Auth Platform audience settings and add the configured account
as a test user.

### No messages found

Confirm that the connectivity test email:

- is still unread;
- has a subject beginning with `[Project Brain]`;
- was sent from the exact `PB_ALLOWED_SENDER` address;
- is less than seven days old.

You can broaden the query temporarily:

```bash
python bridge.py --once --query 'subject:"[Project Brain]"'
```

## Exit criteria for this experiment

The experiment succeeds when the script prints the exact subject and body of
the test email without changing the email or touching the repository.
