#!/bin/bash
#
# Scripts in this directory are run during the build process.
# each script will be uploaded to /tmp on your build droplet,
# given execute permissions and run.  The cleanup process will
# remove the scripts from your build system after they have run
# if you use the build_image task.
#
MELTANO_USER=meltano
MELTANO_ROOT=/var/meltano
MELTANO_VENV=$MELTANO_ROOT/.venv

# setup the meltano root
mkdir -p $MELTANO_ROOT
chown $MELTANO_USER:$MELTANO_USER $MELTANO_ROOT

sudo -H -u $MELTANO_USER python3 -m venv $MELTANO_VENV
sudo -H -u $MELTANO_USER $MELTANO_VENV/bin/pip install --upgrade pip wheel
sudo -H -u $MELTANO_USER $MELTANO_VENV/bin/pip install gunicorn meltano

# create the Meltano project
cd $MELTANO_ROOT
sudo -u $MELTANO_USER $MELTANO_VENV/bin/meltano init project
sudo -u $MELTANO_USER $MELTANO_VENV/bin/meltano --version

# start and enable Meltano
systemctl enable meltano
