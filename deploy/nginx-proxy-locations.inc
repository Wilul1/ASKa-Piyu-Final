# Shared proxy locations (included by nginx.conf and nginx.https.conf).
client_max_body_size 32m;

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

location / {
    proxy_pass http://aska_api;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    # Use $remote_addr only — do not forward client-supplied XFF (spoofable).
    proxy_set_header X-Forwarded-For $remote_addr;
    proxy_set_header X-Forwarded-Proto $scheme;
}
