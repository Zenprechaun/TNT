# Putting the website on Hostinger

The site runs on a **Hostinger VPS**. Hostinger's Web and Cloud hosting plans can't run Python or Django; only its VPS plans can. Hostinger also doesn't offer technical support for Django apps, so this guide and the scripts in the `deploy` folder cover everything the server needs.

## What gets set up

| Piece | What it does |
|-------|--------------|
| Nginx | Receives visitors, handles HTTPS, and limits repeated login attempts |
| Gunicorn | Runs the Django site as a background service named `tahoetable` |
| Let's Encrypt (Certbot) | A free HTTPS certificate that renews itself |
| WhiteNoise | Serves the site's CSS, JavaScript and images |
| SQLite | The database, kept outside the code folder and backed up every night |
| UFW firewall | Allows only SSH, http and https |

## 1. Get the VPS

1. Buy a Hostinger VPS plan. KVM 1 is plenty for this site.
2. Choose **Ubuntu 24.04** as the operating system. Pick plain Ubuntu, not the Django or OpenLiteSpeed template; the setup script installs everything itself.
3. Set a root password, or add an SSH key, when Hostinger asks.
4. In hPanel, open the VPS and note its **IP address**.

## 2. Point the domain at the VPS

The domain is registered at GoDaddy. In GoDaddy's DNS settings for tahoeneighborhoodtable.com:

- Change the **A** record for `@` to the VPS's IP address.
- Make sure `www` points to the same place: a **CNAME** record for `www` pointing to `@`, or an A record with the same IP address.
- Remove any domain forwarding, and any **AAAA** records for `@` or `www`.
- Leave the **MX** and other email records alone, so email to info@tahoeneighborhoodtable.com keeps working. For the same reason, don't switch the domain's nameservers to Hostinger unless you also move the email settings.

DNS changes take anywhere from a few minutes to a few hours. When `nslookup tahoeneighborhoodtable.com` shows the VPS's IP address, continue. The HTTPS step in the setup needs this.

## 3. Upload the project

On your computer, in the folder that holds the zip, run (with your VPS's IP address):

    scp tahoe-neighborhood-table-django.zip root@YOUR_VPS_IP:/root/

An SFTP app such as FileZilla works too.

## 4. Run the setup

Connect to the VPS. hPanel also has a browser terminal you can use instead.

    ssh root@YOUR_VPS_IP

Then run:

    apt-get install -y unzip
    unzip tahoe-neighborhood-table-django.zip
    bash tahoe-neighborhood-table/deploy/setup_server.sh

The script asks for an email address for notices about the HTTPS certificate. It then installs the software, copies the site to `/srv/tahoetable`, creates the settings file with a new secret key, sets up the database, starts the site, gets the HTTPS certificate, turns on the firewall and schedules nightly backups. At the end it asks you to **choose a new password for the Admin account**. Use a strong one, since the original was shared in a chat.

It takes a few minutes. Running it again is safe; it keeps the database and the settings file.

## 5. Check the site

Open https://tahoeneighborhoodtable.com, choose **Log in**, and sign in as Admin with the new password. Signing in only works over https.

## Publishing changes

Changes go live automatically when they're pushed to the `main` branch of the GitHub repository, https://github.com/Zenprechaun/TNT:

1. GitHub Actions runs the tests (`.github/workflows/publish.yml`).
2. If they pass, it moves the `live` branch to that commit.
3. Within a minute the server notices (`deploy/publish.sh`). It backs up the database, puts the new version live and checks that the site answers with it.
4. If the new version doesn't come up properly, the server puts the previous version back.

The workflow run on the repository's **Actions** tab turns green once the website runs the new version, or red with the reason if it didn't. https://tahoeneighborhoodtable.com/healthz shows the version that's running and the result of the latest publish.

To undo a change, revert its commit on `main`. The earlier code is then published the same way.

### Turning on automatic publishing

It's already on for tahoeneighborhoodtable.com. On a new server, after the setup above:

1. Push the code to GitHub with a `live` branch too: `git push origin main main:live`
2. On the server, as root, run:

       bash tahoe-neighborhood-table/deploy/bootstrap_publishing.sh git@github.com:Zenprechaun/TNT.git

   It shows a deploy key. On GitHub, open the repository's **Settings → Deploy keys → Add deploy key**, paste the key, leave **Allow write access** unchecked, and save. The script then continues by itself: it copies the repository to `/srv/tahoetable/repo`, publishes the `live` branch and starts checking it every minute.

### Updating by hand

If automatic publishing is paused, you can still update from a zip:

1. Upload the new zip as in step 3, then on the VPS unzip it over the old folder:

       unzip -o tahoe-neighborhood-table-django.zip

   The live database isn't in that folder, so this doesn't touch it.

2. Run:

       bash tahoe-neighborhood-table/deploy/update.sh

It backs up the database, copies the new code, applies any database changes and restarts the site.

## Everyday tasks

Run these on the VPS as root.

| Task | Command |
|------|---------|
| See whether the site is running | `systemctl status tahoetable` |
| See recent errors | `journalctl -u tahoetable -n 100` |
| Restart the site | `systemctl restart tahoetable` |
| Change someone's password | `sudo -u tahoetable /srv/tahoetable/manage.sh changepassword Admin` |
| Create another admin | `sudo -u tahoetable /srv/tahoetable/manage.sh createsuperuser` |
| Back up the database now | `sudo -u tahoetable /srv/tahoetable/backup_db.sh` |
| Install Ubuntu updates | `apt-get update && apt-get upgrade` |
| See recent publishes | `journalctl -u tahoetable-publish -n 100` |
| Publish the `live` branch now | `tahoetable-publish` |
| Try a version again after it failed | `tahoetable-publish --retry` |
| Pause automatic publishing | `systemctl disable --now tahoetable-publish.timer` |
| Turn automatic publishing back on | `systemctl enable --now tahoetable-publish.timer` |

## Where things live on the server

| Path | What it holds |
|------|---------------|
| `/srv/tahoetable/app` | The website code, replaced on each update |
| `/srv/tahoetable/.env` | Settings and the secret key. Keep it private |
| `/srv/tahoetable/data/db.sqlite3` | The database |
| `/srv/tahoetable/backups` | Database copies from every night and every publish, kept for 14 days |
| `/srv/tahoetable/repo` | The copy of the GitHub repository that publishing uses |
| `/srv/tahoetable/app.previous` | The version that was live before the latest publish |
| `/srv/tahoetable/data/publish-status.json` | The result of the latest publish, also shown at /healthz |
| `/etc/tahoetable` | The server's deploy key, which can only read the GitHub repository |
| `/etc/nginx/sites-available/tahoetable` | The Nginx settings, including the HTTPS lines Certbot added |
| `/etc/systemd/system/tahoetable.service` | The background service that runs the site |

## Restoring a backup

    systemctl stop tahoetable
    cp /srv/tahoetable/backups/db-YYYY-MM-DD-HHMMSS.sqlite3 /srv/tahoetable/data/db.sqlite3
    rm -f /srv/tahoetable/data/db.sqlite3-wal /srv/tahoetable/data/db.sqlite3-shm
    chown tahoetable:tahoetable /srv/tahoetable/data/db.sqlite3
    systemctl start tahoetable

Replace `YYYY-MM-DD-HHMMSS` with the name of the copy you want. Hostinger's weekly VPS backups, in hPanel, are a second safety net.

## If something goes wrong

- **502 Bad Gateway:** the site isn't running. See why with `journalctl -u tahoetable -n 50`.
- **Bad Request (400):** the address you used isn't in `DJANGO_ALLOWED_HOSTS`. Add it in `/srv/tahoetable/.env`, then run `systemctl restart tahoetable`.
- **The HTTPS step failed:** usually the domain doesn't point to the VPS yet. Once it does, run `certbot --nginx --redirect -d tahoeneighborhoodtable.com -d www.tahoeneighborhoodtable.com`.
- **Signing in fails, or says the form has expired:** make sure the address starts with https://.
- **The site doesn't load at all:** if you turned on the firewall in hPanel, allow ports 22, 80 and 443 there.
- **A change doesn't go live:** open the latest run on the repository's **Actions** tab. If the tests failed, it says which. If publishing failed, https://tahoeneighborhoodtable.com/healthz shows the reason, and `journalctl -u tahoetable-publish -n 100` on the server shows the details.
- **Output stops in hPanel's Web Console:** the console pauses while its browser tab is hidden. Bring the tab back; if it's still stuck, press Ctrl+Q.

## Optional extra protection

- Once HTTPS works, set `DJANGO_HSTS_SECONDS=31536000` in `/srv/tahoetable/.env` and restart the site. Browsers will then always use https for it.
- Sign in to the VPS with an SSH key instead of the root password.
