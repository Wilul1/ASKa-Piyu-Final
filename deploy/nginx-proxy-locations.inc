# Shared proxy locations (included by nginx.conf and nginx.https.conf).
# API routes are proxied; everything else is the Flutter web UI (SPA).
client_max_body_size 32m;

# Long-running admin extract/ingest (large handbooks / OCR can exceed 10 min).
proxy_connect_timeout 60s;
proxy_send_timeout 1800s;
proxy_read_timeout 1800s;

location = /auth/login {
    limit_req zone=aska_auth burst=10 nodelay;
    proxy_pass http://aska_api;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    # Use $remote_addr only — do not forward client-supplied XFF (spoofable).
    proxy_set_header X-Forwarded-For $remote_addr;
    proxy_set_header X-Forwarded-Proto $scheme;
}

location = /auth/signup {
    limit_req zone=aska_auth burst=3 nodelay;
    proxy_pass http://aska_api;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    # Use $remote_addr only — do not forward client-supplied XFF (spoofable).
    proxy_set_header X-Forwarded-For $remote_addr;
    proxy_set_header X-Forwarded-Proto $scheme;
}

location = /qa/ask {
    limit_req zone=aska_qa burst=20 nodelay;
    proxy_pass http://aska_api;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    # Use $remote_addr only — do not forward client-supplied XFF (spoofable).
    proxy_set_header X-Forwarded-For $remote_addr;
    proxy_set_header X-Forwarded-Proto $scheme;
}

location = /student/ask {
    limit_req zone=aska_qa burst=20 nodelay;
    proxy_pass http://aska_api;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    # Use $remote_addr only — do not forward client-supplied XFF (spoofable).
    proxy_set_header X-Forwarded-For $remote_addr;
    proxy_set_header X-Forwarded-Proto $scheme;
}

# Admin extract/ingest/rebuild — allow up to 30 minutes for large PDFs/OCR.
location ^~ /admin/ {
    proxy_pass http://aska_api;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $remote_addr;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_connect_timeout 60s;
    proxy_send_timeout 1800s;
    proxy_read_timeout 1800s;
    # Avoid buffering large extract JSON responses mid-stream.
    proxy_buffering off;
}

# Remaining API paths (Flutter SPA owns bare `/` and asset URLs).
location ~ ^/(auth|qa|student|kb|documents|tickets|announcements|health)(/|$) {
    proxy_pass http://aska_api;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $remote_addr;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 120s;
}

# Flutter SPA: never cache the HTML shell / service worker so deploys show up.
location = /index.html {
    root /usr/share/nginx/html;
    add_header Cache-Control "no-store, no-cache, must-revalidate" always;
    add_header Pragma "no-cache" always;
}

location = /flutter_service_worker.js {
    root /usr/share/nginx/html;
    add_header Cache-Control "no-store, no-cache, must-revalidate" always;
    add_header Pragma "no-cache" always;
}

location = /flutter_bootstrap.js {
    root /usr/share/nginx/html;
    add_header Cache-Control "no-store, no-cache, must-revalidate" always;
    add_header Pragma "no-cache" always;
}

location = /version.json {
    root /usr/share/nginx/html;
    add_header Cache-Control "no-store, no-cache, must-revalidate" always;
}

location / {
    root /usr/share/nginx/html;
    try_files $uri $uri/ /index.html;
}
