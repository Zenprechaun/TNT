# Tahoe Neighborhood Table website

The Tahoe Neighborhood Table website, built with Python and Django 5.2, Django's current long-term support release.

## What's here

- **Home page** (`/`): the outreach page, with **Log in** at the top right.
- **Login popup**: people sign in with their username or email address. Anyone with the Admin role goes to the Admin's Dashboard. Everyone else goes to the User's Dashboard.
- **User's Dashboard** (`/dashboard/user/`): the person's account details and roles.
- **Admin's Dashboard** (`/dashboard/admin/`): counts of people, plus a searchable list of everyone, where admins change roles.
- **Full admin site** (`/admin/`): Django's built-in admin, open to anyone with the Admin role. Use **Add a person** there to create accounts.
- **Volunteer sign-up**: the footer's **Volunteer** button opens a pop-up where people pick shifts and sign up. The same sign-up is a full page at `/volunteer/`. See "Volunteer events" below.
- **Health check** (`/healthz`): shows whether the site and its database work, which version of the code is running, and the result of the latest publish.

Without JavaScript, **Log in** opens a full login page (`/accounts/login/`) instead of the popup.

## Roles

Every account has a profile, and each profile has one or more roles. Two roles are built in:

| Role  | What it allows |
|-------|----------------|
| Admin | The Admin's Dashboard, the full admin site, and changing anyone's roles |
| User  | The User's Dashboard |

New accounts start with the User role. Giving someone the Admin role also opens the full admin site to them, and taking it away closes it. Admins can't remove their own Admin role, so the site always keeps at least one admin. More roles can be added in the admin site under **People and roles → Roles**, and checked in code with the `role_required` decorator in `accounts/decorators.py`.

## Volunteer events

Admins manage everything in the admin site under **Volunteers** (the Admin's Dashboard links to it):

- **Events**: add an event, then its shifts in the table at the bottom (role, date, start, end, volunteers needed). The pop-up shows the open event with the soonest shift. Tick **Sign-ups open** to let volunteers sign up, and untick it to close the event.
- **Roles**: the kinds of jobs (Kitchen crew, Serving line…) and their marker colors.
- **Shifts**: how many people each shift has. Open a shift to see its roster, or select shifts and choose **Download the roster** for a spreadsheet.
- **Volunteer sign-ups**: everyone who signed up, searchable. To take someone off a shift, tick **Cancelled**; the spot opens up again.

While an event's sign-ups are closed, only admins see it: the Volunteer button shows them an **Admin preview** they can click through, and nothing sent from a preview is saved. Everyone else sees "There are no volunteer shifts open right now."

The server checks every sign-up: shifts can't be overbooked, nobody can pick overlapping shifts or the same shift twice, and shifts that have started can't be chosen.

The site starts with a sample **Tahoe Community Thanksgiving** event, with sign-ups closed. Edit its details and shifts before opening it, or delete it.

**Email:** until the server has email settings (see `deploy/env.example`), the site doesn't send email, and the confirmation doesn't promise one. With them, volunteers get a copy of their shifts, and the addresses in `VOLUNTEER_NOTIFY_EMAILS` hear about each sign-up.

## The first account

The live site's database holds the first account: username **Admin**, with the Admin and User roles. The database isn't part of the code on GitHub, so a new copy of the code starts without any accounts. To create an admin in your own copy:

    python manage.py createsuperuser

## Run it on your computer

You need Python 3.10 or newer.

    git clone https://github.com/Zenprechaun/TNT.git
    cd TNT
    python -m venv .venv
    source .venv/bin/activate        # on Windows: .venv\Scripts\activate
    pip install -r requirements.txt
    python manage.py migrate
    python manage.py runserver

Then open http://127.0.0.1:8000 and choose **Log in**.

To check that everything works:

    python manage.py test

## Where things are

| Path | What it holds |
|------|---------------|
| `tahoetable/settings.py` | Settings, including `SITE_EMAIL`, the address used for Donate, Volunteer and contact links |
| `accounts/` | Roles, profiles, sign-in, the dashboards, the admin site setup and the tests |
| `pages/` | The home page and the health check |
| `volunteers/` | Volunteer events, shifts and sign-ups: the pop-up, the `/volunteer/` pages, the admin screens, emails and calendar files |
| `templates/` | Page templates. The home page is `pages/home.html`, and its large drawings are in `pages/svg/` |
| `static/site/` | Styles, scripts and images |

## Putting it online

The site runs on a Hostinger VPS at https://tahoeneighborhoodtable.com. **DEPLOY-HOSTINGER.md** covers the server step by step.

**Publishing is automatic.** Every push to the `main` branch on GitHub runs the tests. When they pass, GitHub Actions moves the `live` branch to that commit. The server checks that branch every minute, puts the new version live and makes sure the site answers with it. If it doesn't, the server puts the previous version back. The run on the repository's **Actions** tab shows whether a change went live.

| File | What it does |
|------|--------------|
| `.github/workflows/publish.yml` | Tests each change to `main` and publishes it |
| `deploy/publish.sh` | On the server: checks the `live` branch every minute and puts new versions live |
| `deploy/bootstrap_publishing.sh` | Turns on automatic publishing on a server (once) |
| `deploy/setup_publishing.sh` | Installs the publishing script and its one-minute timer |
| `deploy/setup_server.sh` | First-time setup on a new Ubuntu 24.04 VPS |
| `deploy/update.sh` | Puts a new version live, keeping the database and settings |
| `deploy/nginx.conf` | Web server settings, including limits on repeated login attempts |
| `deploy/gunicorn.conf.py` | Settings for Gunicorn, which runs the Django site |
| `deploy/tahoetable.service` | Keeps the site running in the background |
| `deploy/manage.sh` | Runs Django commands with the live settings |
| `deploy/backup_db.sh` | Copies the database. It runs every night |
| `deploy/env.example` | The live settings, explained line by line |

During server setup you choose a new password for the Admin account.

Two things the site doesn't do yet: people can't reset a forgotten password by email, and there's no sign-up page. Admins add people and change passwords for now.

`db.sqlite3` is listed in `.gitignore`, so accounts and password hashes stay out of version control.
