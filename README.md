# Tahoe Neighborhood Table website

The Tahoe Neighborhood Table website, built with Python and Django 5.2, Django's current long-term support release.

## What's here

- **Home page** (`/`): the outreach page, with **Log in** at the top right.
- **Login popup**: people sign in with their username or email address. Anyone with the Admin role goes to the Admin's Dashboard. Everyone else goes to the User's Dashboard.
- **User's Dashboard** (`/dashboard/user/`): the person's account details and roles.
- **Admin's Dashboard** (`/dashboard/admin/`): counts of people, plus a searchable list of everyone, where admins change roles.
- **Management** (`/dashboard/manage/`): for admins, the site at a glance: email, volunteer events, donations, publishing and backups. See "Management page" below.
- **Full admin site** (`/admin/`): Django's built-in admin, open to anyone with the Admin role. Use **Add a person** there to create accounts.
- **Volunteer sign-up**: the footer's **Volunteer** button opens a pop-up where people pick shifts and sign up. The same sign-up is a full page at `/volunteer/`. See "Volunteer events" below.
- **Health check** (`/healthz`): shows whether the site and its database work, which version of the code is running, and the result of the latest publish.
- **English and Spanish**: the **EN | ES** switch at the top of every page changes the language. See "English and Spanish" below.
- **Donations** (`/donate/`): one-time and monthly donations through Stripe. See "Donations" below.
- **Create an account** (`/accounts/register/`): anyone can make an account with their email, for example to keep their donations and receipts in one place.
- **Forgot your password?** (`/accounts/password/forgot/`): emails a link to choose a new password, once the site can send email. The link works once, for 3 days, and logs the person in.

Without JavaScript, **Log in** opens a full login page (`/accounts/login/`) instead of the popup.

## Roles

Every account has a profile, and each profile has one or more roles. Two roles are built in:

| Role  | What it allows |
|-------|----------------|
| Admin | The Admin's Dashboard, the Management page, the full admin site, and changing anyone's roles |
| User  | The User's Dashboard |

New accounts start with the User role. Giving someone the Admin role also opens the full admin site to them, and taking it away closes it. Admins can't remove their own Admin role, so the site always keeps at least one admin. More roles can be added in the admin site under **People and roles → Roles**, and checked in code with the `role_required` decorator in `accounts/decorators.py`.

## Volunteer events

Admins manage everything in the admin site under **Volunteers** (the Admin's Dashboard links to it):

- **Events**: add an event, then its shifts at the bottom (role, date, start, end, volunteers needed). The pop-up shows the open event with the soonest shift. Tick **Sign-ups open** to let volunteers sign up, and untick it to close the event.
- **Roles**: the kinds of jobs (Kitchen crew, Serving line…) and their marker colors.
- **Shifts**: how many people each shift has. Open a shift to see its roster, or select shifts and choose **Download the roster** for a spreadsheet.
- **Volunteer sign-ups**: everyone who signed up, searchable. To take someone off a shift, tick **Cancelled**; the spot opens up again.

While an event's sign-ups are closed, only admins see it: the Volunteer button shows them an **Admin preview** they can click through, and nothing sent from a preview is saved. Everyone else sees "There are no volunteer shifts open right now."

The server checks every sign-up: shifts can't be overbooked, nobody can pick overlapping shifts or the same shift twice, and shifts that have started can't be chosen.

The site starts with a sample **Tahoe Community Thanksgiving** event, with sign-ups closed. Edit its details and shifts before opening it, or delete it.

**Email:** once an email service is connected on the Management page, volunteers get a copy of their shifts, and the organizers listed there hear about each sign-up. Until then the confirmation doesn't promise an email. See "Email" below.

## Donations

The **Donate** buttons open the donation page at `/donate/`:

- Donors choose **one-time** or **monthly**, then $10, $25, $50, $100, $250 or another amount ($5 to $10,000). They can add a little to cover the card fee.
- They can donate as a guest, or log in or create an account first so their donations and receipts stay together in their dashboard.
- They pay on Stripe's own secure page (Stripe Checkout), in Spanish when the site is in Spanish. The site never sees card numbers.
- Afterwards the thank-you page is their receipt: receipt number, date, amount and the 501(c)(3) statement, ready to print or save. The link keeps working, and signed-in donors find every receipt in their dashboard. Once the site can send email, donors also get the receipt by email.
- Monthly donors change or stop their donation on a Stripe page: from their dashboard, or through the link on their receipt if they gave as a guest (Stripe emails them a sign-in link).

Admins see every donation under **Donations** in the admin site, where they can download a spreadsheet. The Admin's Dashboard and the Management page show this year's total and the monthly donors.

**Before Stripe is connected**, the Donate button opens an email for visitors, as before, and admins get the whole donation page as a preview that charges nothing. DEPLOY-HOSTINGER.md explains connecting Stripe.

**Receipts** say Tahoe Neighborhood Table is a 501(c)(3) nonprofit and donations are tax-deductible. Set `DONATIONS_TAX_DEDUCTIBLE=false` in the server settings if that ever stops being true, and `DONATIONS_TAX_ID` to print the EIN.

**How it's built:** `donations/services.py` opens Stripe Checkout and records what Stripe reports. Stripe tells the site about payments through a webhook (`/donate/stripe/webhook/`), and every message must carry Stripe's signature. `donations/stripe_api.py` holds every call to Stripe, and the tests replace it, so they never contact Stripe.

## Email

The site sends email through an email service: **Resend** is recommended (free for 3,000 emails a month), and Brevo, Google Workspace or any SMTP service works too. An admin connects it on the Management page (`/dashboard/manage/#email`), and DEPLOY-HOSTINGER.md, "Turning on email", has the steps. The site emails:

- volunteers a copy of their shifts, in the language they signed up in,
- the organizers listed on the Management page about each new sign-up,
- donors their receipt,
- a link to choose a new password to anyone who asks for one.

The Management page turns each of these on or off (except password resets), sends test emails, and checks the domain's email records in DNS.

**Every email is kept** for six months (`emails.Email`), sent or not, with the email service's answer when one didn't go out. The Management page lists the latest and can send any of them again, so a receipt that failed while the email service was down, or that was "sent" while email was off, isn't lost. Password reset emails are the exception: their links are never stored.

**How it's built:** `emails/sending.py` has `send()`, which every email goes through. The email service's API key or password is stored encrypted in the database, with a key made from `DJANGO_SECRET_KEY` (`emails/secrets.py`). Settings in the server's `.env` file (`EMAIL_HOST` and the rest, see `deploy/env.example`) also work, and are used when the Management page has none. Locally, set `EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend` to see emails in the terminal instead of sending them.

## Management page

`/dashboard/manage/`, for admins (the **Management** link at the top of the dashboards):

- **At a glance:** a tile each for email, donations, volunteers, publishing and backups, marked when something needs attention.
- **Email:** connect the email service, choose what the site emails and who hears about new volunteers, send a test, check the domain's DNS records, and see recent emails with a **Send again** button.
- **Volunteer events:** upcoming events with how full they are, links to edit each one, its sign-up page and a roster spreadsheet, plus the latest sign-ups.
- **Donations:** this year's total, the monthly donors, whether Stripe's payment updates are connected, the latest donations and a spreadsheet of the year.
- **Publishing and backups:** the version that's live and how the latest publish went, and the newest nightly backup.

Everything else is in the full admin site, which the page links to.

## English and Spanish

Every page is in English and Spanish. The first visit follows the browser's language, so a phone set to Spanish gets the Spanish site. The **EN | ES** switch at the top of each page (and in the dashboards and the admin's top bar) changes it, and the site remembers the choice for a year. The Spanish uses the formal *usted*.

**Event text.** Each event, role and shift has a Spanish box next to each English one in the admin. Visitors who choose Spanish see the Spanish text, or the English where a Spanish box is empty, so fill those in before opening sign-ups. Dates and times follow the language on their own ("Miércoles 25 de noviembre, 2:00 p.m.").

**Emails.** Volunteers get their confirmation in the language they signed up in. Organizers get theirs in English, with the volunteer's language noted, and the admin's sign-up list and roster downloads have a **Language** column.

**Changing the site's own text.** Text in templates, Python and scripts is marked for translation (`{% translate %}` and `{% blocktranslate %}` in templates, `gettext` in Python and scripts). The Spanish lives in `locale/es/LC_MESSAGES/`: `django.po` for pages and `djangojs.po` for scripts. After adding or changing text:

    python manage.py translations update    # adds the new English to the .po files
    # write the Spanish for each new entry (msgstr) in the .po files
    python manage.py translations compile   # writes the .mo files Django reads
    python manage.py translations check     # lists anything still missing

These commands don't need GNU gettext installed. The tests run the same check, so a change with untranslated text, or with a translation that drops a placeholder like `%(name)s` or a link, doesn't get published.

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
| `accounts/` | Roles, profiles, sign-in, password resets, the dashboards (the Management page is `accounts/manage.py`), the admin site setup and the tests |
| `pages/` | The home page, the health check, publishing and backup status (`pages/status.py`) and the `translations` command (`pages/translation_files.py`) |
| `emails/` | Email: sending and keeping a copy of each email, the email service settings, DNS checks and the `send_test_email` command |
| `locale/es/` | The Spanish translations. See "English and Spanish" |
| `volunteers/` | Volunteer events, shifts and sign-ups: the pop-up, the `/volunteer/` pages, the admin screens, emails and calendar files |
| `donations/` | Donations through Stripe: the `/donate/` pages, receipts, the webhook, the admin screens and the `connect_stripe` command |
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

Once email is on, anyone who forgets their password can reset it from **Forgot your password?** in the login popup. Admins can also change any password in the admin site.

`db.sqlite3` is listed in `.gitignore`, so accounts and password hashes stay out of version control.
