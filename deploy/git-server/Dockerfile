FROM python:3.12-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends git openssh-server \
    && useradd --create-home --shell /bin/sh git \
    && usermod --password '*' git \
    && mkdir -p /run/sshd /srv/git /var/lib/aegis/reports /var/lib/aegis/ssh

WORKDIR /opt/aegis
COPY deploy/git-server/requirements.txt /tmp/aegis-requirements.txt
RUN pip install --no-cache-dir -r /tmp/aegis-requirements.txt
COPY src ./src
COPY tests/fixtures/companies/company_a_finscore /opt/aegis/seed
COPY deploy/git-server/entrypoint.py /opt/aegis/entrypoint.py
COPY deploy/git-server/ssh_command.py /usr/local/bin/aegis-ssh-command
COPY deploy/git-server/hooks /opt/aegis/hooks
COPY deploy/git-server/sshd_config /etc/ssh/aegis_sshd_config
RUN chmod 755 /usr/local/bin/aegis-ssh-command /opt/aegis/hooks/*

EXPOSE 22
ENTRYPOINT ["python", "/opt/aegis/entrypoint.py"]
