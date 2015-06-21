# callblock - Python junk call blocker.

# Description

Home Page: http://dmeekins.github.io/callblock/

Callblock is a simple daemon written in Python that uses a modem to listen for
incoming calls and issues a hangup if caller ID data matches a blacklist. It is
based off the "jcblock" project by Walter Heath (jcblock.sourceforge.net).

It contains a configuration file to run as a service under systemd.

I use a TRENDnet USB modem (TFM-561U), as mentioned inn the jcblock README.

# Installing

Requires: Python3

Manual install example for CentOS 7:

    cp callblock.py /usr/local/sbin/callblock.py
    cp callblock.conf /etc/callblock.conf
    cp callblock.service /usr/lib/systemd/system/callblock.service
    systemctl enable callblock.service
    systemctl start callblock.service


Manual execution without running as a service:

  callblock.py -c callblock.conf
