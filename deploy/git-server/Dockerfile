FROM python:3.12-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends git openssh-server \
    && useradd --create-home --shell /bin/sh git \
    && usermod --password '*' git \
    && mkdir -p /run/sshd /srv/git /var/lib/graphite/reports /var/lib/graphite/ssh

WORKDIR /opt/graphite
COPY deploy/git-server/requirements.txt /tmp/graphite-requirements.txt
RUN pip install --no-cache-dir -r /tmp/graphite-requirements.txt
COPY src ./src
COPY tests/fixtures/companies/company_a_finscore /opt/graphite/seed
COPY deploy/git-server/entrypoint.py /opt/graphite/entrypoint.py
COPY deploy/git-server/ssh_command.py /usr/local/bin/graphite-ssh-command
COPY deploy/git-server/hooks /opt/graphite/hooks
COPY deploy/git-server/sshd_config /etc/ssh/graphite_sshd_config
RUN chmod 755 /usr/local/bin/graphite-ssh-command /opt/graphite/hooks/*

EXPOSE 22
ENTRYPOINT ["python", "/opt/graphite/entrypoint.py"]
