# The Channel Desk: public news site (for students)

A separate, read-only Flask app. No sign-in, no register, no staff links: visitors see only
the news. It shares the **database** and the **uploads folder** with the staff app, so a work
appears here as soon as the Adviser gives final approval (status `approved`).

```
flask --app app run --port 5001      # students:  http://localhost:5001
flask --app ../app run               # staff:     http://localhost:5000  (in the staff folder)
```

## Settings
It reads the staff app's `.env` automatically (database login), looking in `./.env`,
`../.env`, then `../channeldesk/.env`. To override, create a `.env` here. Optional keys:

- `NEWS_SECRET_KEY`: this site's own session key
- `UPLOAD_FOLDER`: full path to the staff app's `uploads` folder (default: `../uploads`
  or `../channeldesk/uploads`)

## Moving this folder
It can live inside the staff project (as now) or beside it, e.g.
`htdocs/channeldesk-news` next to `htdocs/channeldesk`. Nothing else changes.

On first visit it creates three small tables: `post_reactions`, `post_views`, `poll_votes`
(its DB user needs CREATE rights; otherwise run the SQL at the bottom of the staff `schema.sql`).
