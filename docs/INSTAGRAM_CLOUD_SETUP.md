# Put the Instagram publisher in the cloud

This page is the one-time setup. After it, a cloud computer posts **one** file every evening at 7:30 PM India time. You keep adding photos and videos to Google Drive. You do not start the computer yourself.

The computer uses the code in `automation/instagram-autoposter`. It does not invent a new publisher.

## What happens each evening

1. It opens the newest copy of this project.
2. It looks in your Posts, Stories, and Reels folders.
3. It picks the **oldest** file that has never been posted.
4. If that file is a photo, it picks one song from your Music folder by looking at the picture (romantic, cinematic, instrumental, or celebration).
5. It publishes that one item to Instagram `@aamodpisatphotography`.
6. A Story has no caption. It does tag `@aamod.pisat` and `@akanksha_pednekar_pisat`. A Post or Reel gets a caption. A video keeps its own sound.
7. Only after Instagram confirms the post, it **permanently deletes that one file** from Drive so it stops using storage.

Trash does not free space. The delete is permanent. Copy anything you still want into a different folder before you turn this on. The Music folder is never deleted.

If tonight does not publish, the file stays on Drive.

The first evening also removes older files that the private log already marks as published, if they are still in Posts, Stories, or Reels. That includes the 14 November 2026 Story test file if it is still in Stories. The private log itself is kept, so those files are not posted again.

## Folders

Put new files only in these private folders:

- [Posts](https://drive.google.com/drive/folders/1glY01mxz-VIp8CNUQJlxJZU9_s7Suvuj) — JPEG or PNG, up to 25 MB
- [Stories](https://drive.google.com/drive/folders/1Y6VGwznezGGfYiHfWXaFfig60KHw6ij9) — JPEG, PNG, MP4, or MOV. Photos up to 25 MB. Videos up to 250 MB and up to 60 seconds
- [Reels](https://drive.google.com/drive/folders/1d2ED3R33W7vmvk1r0P-nax-Cx_Yl2YoC) — MP4 or MOV only, 3 seconds to 15 minutes, up to 250 MB
- [Music](https://drive.google.com/drive/folders/1f3rnLYZA5vNAMb3Jg3IQlWH2mcCaXHVd) — MP3 up to 25 MB. Name the file with romantic, cinematic, classical, piano, instrumental, celebration, festive, or upbeat. These files stay.

Do not make these folders public.

## Step 1. Open the cloud computer settings

1. Open [Cloud Agents](https://cursor.com/agents).
2. Open the environment named **social-media-publisher**. The setup guide is [here](https://cursor.com/docs/cloud-agent/setup). Environment settings are [here](https://cursor.com/docs/cloud-agent/settings).
3. When this project shows a proposed environment, press **Save**. That installs FFmpeg (the tool that builds the Story video) and the Python packages. Until a build succeeds, a new computer can start without those tools and the evening run will stop before posting.

## Step 2. Add secrets

In that environment, open **Secrets**. Add each name below. Paste the value only into the secret box. Do not paste tokens into chat, into a file in this project, or into an email.

You already used these for the Story test on 14 November 2026. Use those same values.

| Name | What to paste |
| --- | --- |
| `INSTAGRAM_ACCESS_TOKEN` | The long-lived Facebook Page token. How it was created is in [META_SETUP.md](META_SETUP.md). |
| `INSTAGRAM_BUSINESS_ACCOUNT_ID` | The numeric Instagram id, not the @ name. |
| `GCS_BUCKET_NAME` | The private Google Cloud bucket that already stores the posting history. |
| `GCS_SERVICE_ACCOUNT_JSON` | The whole Storage key file, pasted as JSON. This key is for storage only. It must not be a Drive key. |
| `OPENAI_API_KEY` | Needed for Post and Reel captions. Stories can publish without it. |
| `META_GRAPH_VERSION` | `v27.0` |
| `GOOGLE_OAUTH_CLIENT_ID` | From Step 3. |
| `GOOGLE_OAUTH_CLIENT_SECRET` | From Step 3. |
| `GOOGLE_DRIVE_REFRESH_TOKEN` | From Step 3. |

If a name is rejected, these aliases also work for the Instagram token and id: `META_PAGE_ACCESS_TOKEN` and `META_IG_USER_ID`.

## Step 3. Let the computer download and delete your Drive files

Cursor’s Google Drive connection can list files and show a photo. It cannot reliably download a wedding photo or a Reel, because that download is capped at 10 MB. Deleting through that connection only moves a file to trash, and trash still uses your storage.

The publisher therefore uses a separate Google login that you approve once.

1. Open [Google Cloud credentials](https://console.cloud.google.com/apis/credentials) in the same project that owns the Storage key.
2. Open [the Drive API library](https://console.cloud.google.com/apis/library/drive.googleapis.com) and press **Enable** if it is not already on.
3. Configure the [OAuth consent screen](https://console.cloud.google.com/apis/credentials/consent) as an External or Internal app that you yourself can use. Add the scope `https://www.googleapis.com/auth/drive` (see, download, and delete files you own). Add your Google account as a test user if the app is in testing.
4. Create an OAuth client of type **Desktop app**. Copy the client id and client secret into the two secrets in Step 2.
5. On your own computer, in a terminal, from a checkout of this project, run the bootstrap once (`automation/instagram-autoposter/bootstrap.sh`), then:

```bash
cd automation/instagram-autoposter
GOOGLE_OAUTH_CLIENT_ID="paste-id" GOOGLE_OAUTH_CLIENT_SECRET="paste-secret" \
  .venv/bin/python - <<'PY'
from google_auth_oauthlib.flow import InstalledAppFlow
import os
flow = InstalledAppFlow.from_client_config(
    {"installed": {
        "client_id": os.environ["GOOGLE_OAUTH_CLIENT_ID"],
        "client_secret": os.environ["GOOGLE_OAUTH_CLIENT_SECRET"],
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": ["http://localhost"],
    }},
    ["https://www.googleapis.com/auth/drive"])
creds = flow.run_local_server(port=0)
print(creds.refresh_token)
PY
```

That snippet is not part of the daily run. It opens a browser. Sign in as the owner of the folders and press Allow. The terminal prints a refresh token. Paste that into the `GOOGLE_DRIVE_REFRESH_TOKEN` secret. Close the terminal. Do not commit the token and do not send it in chat.

If the terminal prints nothing, open [Google account permissions](https://myaccount.google.com/permissions), remove this app, and run the snippet again so Google issues a refresh token.

The daily computer does not include `google-auth-oauthlib`. You only need that package on your own computer for this one-time login: `pip install google-auth-oauthlib`.

## Step 4. Connect Google Drive on the automation

The evening job still uses the Google Drive connection to list folders and look at a photo.

1. Open [New automation](https://cursor.com/automations/new).
2. Name: `Instagram evening publisher`
3. Repository: `aamodpisat/social-media-publisher`
4. Environment: `social-media-publisher`
5. Schedule: every day at **7:30 PM**. If you can pick a timezone, choose **Kolkata / India**. If the box wants a UTC cron expression, use `30 14 * * *`. India does not change clocks, so this stays 7:30 PM.
6. Turn on the Google Drive tool and finish Google’s Allow prompt with the account that owns the folders.
7. Allow the automation to open a GitHub pull request when a code fix is needed.
8. Paste the whole file [automation/instagram-autoposter/CLOUD_AGENT_PROMPT.md](../automation/instagram-autoposter/CLOUD_AGENT_PROMPT.md) into the instructions.
9. Save and leave it enabled.

## Step 5. Read the first evening’s result

Open the run from [cursor.com/agents](https://cursor.com/agents). A finished run says one of:

- published a Story, Post, or Reel, and the Drive file was deleted
- published, but the Drive file is still there and will be deleted next evening
- nothing new to post
- needs your attention, with the clicks below

## When it stops and asks you to do something

Do not delete the posting history in Google Cloud. Do not create a new empty log.

| What the run says | What you do |
| --- | --- |
| A secret name is `MISSING` | Add that secret in the environment. The run lists names only, never the secret itself. |
| Drive says Connect or Reconnect | Open the run and press the connect button. |
| Instagram handle does not match | The token is for a different account than `@aamodpisatphotography`. Create a Page token for the right account. See [META_SETUP.md](META_SETUP.md). |
| Token expired or rejected | Open the [token debugger](https://developers.facebook.com/tools/debug/accesstoken/), issue a new long-lived Page token, and replace `INSTAGRAM_ACCESS_TOKEN`. |
| Story tags were rejected | Confirm that `@aamod.pisat` and `@akanksha_pednekar_pisat` allow tags from this professional account. Do not post the Story without the tags. The file stays on Drive. |
| FFmpeg is missing | Save the environment proposal so the next computer installs FFmpeg, then run the automation again the next evening. |
| Drive login was rejected | Repeat Step 3 and replace `GOOGLE_DRIVE_REFRESH_TOKEN`. |
| The Cloud posting record is missing or damaged | Restore the current Google Cloud object `instagram-state/v1/<account id>/<root folder id>/processed_images.json` from its latest valid version. Do not run a command that creates a blank history. |
| A pull request was opened | Instagram was not given a second file. Review the pull request and merge it if the fix is right. The original file is still on Drive until a later evening publishes it. |

A code crash can be fixed by the agent in a pull request. A login, token, tag, or history problem cannot. Those wait for you.
