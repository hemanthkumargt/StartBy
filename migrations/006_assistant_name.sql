-- Each user can name their voice assistant (NULL = use the site default, ASSISTANT_NAME).
ALTER TABLE users ADD COLUMN assistant_name TEXT;
