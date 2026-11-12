# Meta credentials for publishing

Use a **test Facebook Page** and a **Professional Instagram** account first. Never paste tokens into chat, templates, or the LLM.

## 1. Accounts

- Convert Instagram to **Professional** (Business or Creator).
- Link it to a **Facebook Page** you admin.
- Personal Instagram accounts cannot use Content Publishing.

## 2. Create a Meta app

1. Open [developers.facebook.com](https://developers.facebook.com) and create an app (type **Business**).
2. Add **Facebook Login** / Graph API access for your admin user.
3. Request these permissions (Development mode is enough while you are a role on the app):
   - `pages_show_list`
   - `pages_read_engagement`
   - `pages_manage_posts`
   - `instagram_basic`
   - `instagram_content_publish`
   - `business_management` if the Page lives in Business Manager

## 3. Page access token

In [Graph API Explorer](https://developers.facebook.com/tools/explorer):

1. Select your app.
2. Get a user token as a Page admin with the permissions above.
3. Call `GET me/accounts` and copy the **Page access token** for the Page you will post to.
4. Exchange it for a **long-lived** Page token (Meta’s token debugger / exchange endpoint).
5. Put that value only in `.env` as `META_PAGE_ACCESS_TOKEN`.

If a token leaks: revoke it in Meta Business settings, issue a new one, replace `.env`. Confirm `.env` was never committed (`git status` / `.gitignore`).

## 4. IDs

- `META_PAGE_ID` — the numeric Page id (`me/accounts` or Page About).
- `META_IG_USER_ID` — `GET /{page-id}?fields=instagram_business_account` and use the returned id (not the @username).
- `META_GRAPH_VERSION` — e.g. `v21.0`.

## 5. Contentstack asset hosting

The publisher will upload each selected local file to Contentstack Assets, then pass the returned asset CDN URL to Meta. Meta cannot fetch a local `file://` path. Contentstack direct asset URLs are publicly accessible, so use this only for media you are comfortable making accessible by URL.

Set these values in the local `.env`:

- `CONTENTSTACK_API_KEY` — Stack API key, found in the stack's Settings under API Credentials. This identifies the stack; it is not the upload credential.
- `CONTENTSTACK_MANAGEMENT_TOKEN` — Management Token for the classic Content Management API (CMA) asset upload endpoint. Keep it secret and scope it to asset upload/manage permissions where supported.
- `CONTENTSTACK_API_HOST` — regional Contentstack CMA host, e.g. `https://api.contentstack.io`; select the host for your stack's region.
- `CONTENTSTACK_IMAGE_HOST` — image CDN host, set to `https://images.contentstack.io`.
- `CONTENTSTACK_VIDEO_HOST` — video CDN host, set to `https://assets.contentstack.io`.

The local publisher uploads each selected file through classic CMA with the Stack API key and Management Token, then uses the returned asset path with the image or video CDN host. Never send Contentstack credentials to the caption-generation model or browser UI. Uploaded media is publicly accessible by URL.

For the local Codex scheduled automation, first call `next-media` to get one eligible path and media type. Have the agent inspect that media and write the caption, then call `publish-one --media <path> --caption <caption>`. This uses Codex's model and does not require `LLM_API_KEY`. `publish-one` still supports direct caption generation when an LLM API key is configured. Instagram-to-Facebook sharing is handled by Meta; the app does not separately publish the same item to Facebook. Install ffmpeg when using direct API captioning for video.

## 6. App Review (live / customer accounts)

Development mode can only publish to users/Pages with a role on the app. For a live business account, submit App Review for `instagram_content_publish` and `pages_manage_posts`.

## 7. Smoke test

```
GET /{ig-user-id}?fields=id,username
```

Then generate a week, approve the batch, and publish **one feed post** before enabling daily `publish-due`.
