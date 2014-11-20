"""
nginx log parser for 'dogstreams'.

setup:

1. instal datadog-agent:
   DD_API_KEY=[YOU KEY] bash -c "$(curl -L https://raw.githubusercontent.com/DataDog/dd-agent/master/packaging/datadog-agent/source/install_agent.sh)"

2. add this file to (/opt/datadog-agent/agent/dogstream/nginx.py)

3. add this line to your Agent configuration (/etc/dd-agent/datadog.conf)
   dogstreams: /path/to/log1:/opt/datadog-agent/agent/dogstream/nginx.py:parse

4. check Agent collector logs (/var/log/datadog/collector.log)

"""

import time
from datetime import datetime
import re
import sys

"""
nginx.conf:
log_format timed_combined
    '$remote_addr - $remote_user [$time_local]
    '"$request" $status $body_bytes_sent '
    '"$http_referer" "$http_user_agent" '
    '$request_time $upstream_response_time $pi
"""
LOG_FORMAT_TIMED_COMBINED = "(?P<ip_address>\S*)\s-\s(?P<requesting_user>\S*)\s\[(?P<timestamp>.*?)\]\s{1,2}\"(?P<method>\S*)\s*(?P<request>\S*)\s*(HTTP\/)*(?P<http_version>.*?)\"\s(?P<response_code>\d{3})\s(?P<size>\S*)\s\"(?P<referrer>[^\"]*)\"\s\"(?P<client>[^\"]*)\"\s(?P<service_time>\S*)\s(?P<application_time>\S*)\s(?P<pipe>\S*)"

STATUS_REGEX = {
    '4XX': "4[0-9]{2}", '5XX': "5[0-9]{2}"
}

METRICS = {
    '4XX':      'nginx.net.4xx_status',
    '5XX':      'nginx.net.5xx_status',
    'APP_TIME': 'nginx.net.app_time',
}

def parse(log, line):
    parsed = parseline(line)
    #log.info(parsed)
    call = buildapicall(parsed)
    return call

def parseline(line):
    """
    takes a log line and returns object like this:

        'timestamp': '17/Nov/2014:13:11:26 +0100',
        'http_version': '1.1',
        'response_code': '404',
        'service_time': '0.640',
        'pipe': '.',
        'client': 'Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.36 (KHTML, i/537.36)',
        'referrer': 'https://preis24.de/handy-mit-vertrag/?tr=SEM-handyvA',
        'path': '/images/rebrush/teaser-device/',
        'ip_address': '80.255.12.114',
        'method': 'GET',
        'application_time': '0.640',
        'size': '16906'

    see also https://github.com/Yipit/parsible
    """
    regex = re.compile(LOG_FORMAT_TIMED_COMBINED)
    r = regex.search(line)
    result_set = {}
    if r:
        for k, v in r.groupdict().iteritems():
            if v is None or v is "-":
                continue
            if "request" in k:
                if "?" in v:
                    request = v.partition("?")
                    path = request[0]
                    query = request[2]
                    result_set["path"] = path
                    result_set["query"] = query
                    r.groupdict().pop(k)
                    continue
                else:
                    result_set["path"] = r.groupdict().pop(k)
                    continue
            result_set[k] = r.groupdict().pop(k)
    return result_set

def buildapicall(result):
    """
    return api call like

        [("nginx.net.4xx_status", 1416226286.0, 1, {"metric_type": "counter"}),
        ('nginx.net.app_time', 1416226286.0, '0.640', {'metric_type': 'gauge'})]

    see also http://docs.datadoghq.com/guides/logs/
    """
    apicall = []

    try:
        log_timestamp = result['timestamp']
    except KeyError:
        return None

    try:
        response_code = result['response_code']
    except KeyError:
        return None

    timestamp = getTimestamp(log_timestamp)

    if isHttpResponse4XX(response_code):
        apicall.append((METRICS['4XX'], timestamp, 1, {'metric_type': 'counter'}))

    if isHttpResponse5XX(response_code):
        apicall.append((METRICS['5XX'], timestamp, 1, {'metric_type': 'counter'}))

    try:
       application_time = result['application_time']
    except KeyError:
        application_time = None

    if application_time is not None:
        apicall.append((METRICS['APP_TIME'], timestamp, application_time, {'metric_type': 'gauge'}))

    return apicall

def getTimestamp(line):
    line_parts = line.split()
    dt = line_parts[0]
    date = datetime.strptime(dt, "%d/%b/%Y:%H:%M:%S")
    date = time.mktime(date.timetuple())
    return date

def isHttpResponse4XX(line):
    response = re.search(STATUS_REGEX['4XX'], line)
    return (response is not None)

def isHttpResponse5XX(line):
    response = re.search(STATUS_REGEX['5XX'], line)
    return (response is not None)

################################ TEST

def test400(log):
    test_line = '80.255.12.114 - - [17/Nov/2014:13:11:26 +0100] "GET /images/rebrush/teaser-device/ HTTP/1.1" 404 16906 "https://preis24.de/handy-mit-vertrag/?tr=SEM-handyvA" "Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.36 (KHTML, i/537.36)" 0.640 0.640 .'
    expected = [("nginx.net.4xx_status", 1416226286.0, 1, {"metric_type": "counter"}), ('nginx.net.app_time', 1416226286.0, '0.640', {'metric_type': 'gauge'})]
    actual = parse(log, test_line)
    assert expected == actual, "%s != %s" % (expected, actual)
    print 'test 400 pass'

def test200(log):
    test_line = '80.255.12.114 - - [17/Nov/2014:13:11:26 +0100] "GET /images/rebrush/teaser-device/ HTTP/1.1" 200 16906 "https://preis24.de/handy-mit-vertrag/?tr=SEM-handyvA" "Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.36 (KHTML, i/537.36" 0.640 0.640 .'
    expected = [('nginx.net.app_time', 1416226286.0, '0.640', {'metric_type': 'gauge'})]
    actual = parse(log, test_line)
    assert expected == actual, "%s != %s" % (expected, actual)
    print 'test 200 pass'

def testTime(log):
    test_line = '192.168.24.1 - - [18/Nov/2014:18:03:42 +0000]  "GET /bundles/sonataadmin/vendor/select2/select2.png HTTP/1.1" 304 0 "http://api.preis24.de/bundles/sonataadmin/vendor/select2/select2.css" "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Ubuntu Chromium/37.0.2062.120 Chrome/37.0.2062.120 Safari/537.36" 0.000 - .'
    expected = []
    actual = parse(log, test_line)
    assert expected == actual, "%s != %s" % (expected, actual)
    print 'test pass'

################################

if __name__ == "__main__":
   import sys
   import pprint
   import logging

   logging.basicConfig()
   #logging.basicConfig(level=logging.DEBUG)
   log = logging.getLogger()
   lines = open(sys.argv[1]).readlines()
   pprint.pprint([parse(log, line) for line in lines])

   #test400(log)
   #test200(log)
   #testTime(log)