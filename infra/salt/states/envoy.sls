envoy_user:
  user.present:
    - name: envoy
    - system: True

/etc/sovereign:
  file.directory:
    - user: envoy
    - group: envoy
    - mode: '0750'

/etc/systemd/system/envoy.service:
  file.managed:
    - contents: |
        [Unit]
        Description=Sovereign Envoy
        After=network-online.target
        [Service]
        User=envoy
        ExecStart=/usr/local/bin/envoy -c /etc/sovereign/envoy.yaml --service-cluster sovereign
        Restart=always
        [Install]
        WantedBy=multi-user.target
