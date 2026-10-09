"""Own Nginx prefix routing for the five upstream WireMock services.

Must not capture traffic, retry requests or persist configuration/data.
Contract: OFFICIAL-FIVE.md.
"""

NGINX_IMAGE = ('nginx:stable-alpine@sha256:'
               '0985e772fb9f729e6fa0980da05fca5d9c468e870eed43071545afa9d2e27d94')


def nginx_config():
    upstreams = '\n'.join(
        f'  upstream mock_{i} {{ server wiremock-{i}:8080; keepalive 256; }}'
        for i in range(1, 6))
    routes = '\n'.join(
        f'    location = /mock-{i} {{ return 308 /mock-{i}/$is_args$args; }}\n'
        f'    location /mock-{i}/ {{ proxy_pass http://mock_{i}/; }}'
        for i in range(1, 6))
    return '''worker_processes 2;
worker_rlimit_nofile 131072;
pid /tmp/nginx.pid;
error_log /dev/stderr warn;
events { worker_connections 65536; }
http {
  access_log off;
  client_body_temp_path /tmp/client_body;
  proxy_temp_path /tmp/proxy;
  fastcgi_temp_path /tmp/fastcgi;
  uwsgi_temp_path /tmp/uwsgi;
  scgi_temp_path /tmp/scgi;
  client_max_body_size 0;
  proxy_http_version 1.1;
  proxy_set_header Connection "";
  proxy_set_header Host $http_host;
  proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
  proxy_set_header X-Forwarded-Proto $scheme;
  proxy_connect_timeout 5s;
  proxy_read_timeout 75s;
  proxy_send_timeout 75s;
  proxy_next_upstream off;
  proxy_buffering off;
  proxy_request_buffering off;
  proxy_cache off;
  absolute_redirect off;
''' + upstreams + '''
  server {
    listen 8080 backlog=4096;
    location = /healthz { default_type text/plain; return 200 "ok\\n"; }
''' + routes + '''
    location / { return 404; }
  }
}
'''


def nginx_service():
    script = ("cat > /tmp/nginx.conf <<'WIREMOCK_NGINX_CONFIG'\n"
              + nginx_config().replace('$', '$$')
              + "WIREMOCK_NGINX_CONFIG\nexec nginx -c /tmp/nginx.conf -g 'daemon off;'\n")
    return {
        'image': NGINX_IMAGE,
        'entrypoint': ['/bin/sh', '-ec'],
        'command': [script],
        'ports': [{'target': 8080, 'published': 19081, 'protocol': 'tcp', 'mode': 'ingress'}],
        'read_only': True,
        'volumes': [{'type': 'tmpfs', 'target': '/tmp', 'tmpfs': {'size': 67108864}}],
        'ulimits': {'nofile': {'soft': 131072, 'hard': 131072}},
        'healthcheck': {
            'test': ['CMD', 'wget', '-q', '-O', '/dev/null', 'http://127.0.0.1:8080/healthz'],
            'interval': '10s', 'timeout': '5s', 'retries': 12,
        },
        'stop_grace_period': '90s',
        'deploy': {
            'replicas': 1,
            'placement': {'constraints': ['node.hostname == ${NGINX_NODE:?set Swarm node hostname}']},
            'resources': {'limits': {'cpus': '2', 'memory': '512M'}},
            'restart_policy': {'condition': 'on-failure', 'delay': '5s'},
            'update_config': {'parallelism': 1, 'order': 'stop-first'},
            'rollback_config': {'parallelism': 1, 'order': 'stop-first'},
        },
        'logging': {'driver': 'json-file', 'options': {'max-size': '10m', 'max-file': '3'}},
    }
