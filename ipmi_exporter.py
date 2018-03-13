import subprocess
import itertools
import time
import logging
import os
import re
from multiprocessing import Process, Manager
from prometheus_client import start_http_server, Summary
from prometheus_client.core import GaugeMetricFamily, REGISTRY


try:
    IPS = os.getenv('TARGET_IPS').split(',')
except AttributeError:
    raise Exception("Mandatory `TARGET_IPS` environment variable is not set")

IPMI_USER = os.getenv('IPMI_USER', 'ADMIN')
IPMI_PASSWD = os.getenv('IPMI_PASSWD', 'ADMIN')
IPMI_PRIV = os.getenv('IPMI_PRIV', 'USER')

SKIP_PARAM=[" no reading"]

REQURED = [
    "CPU1 Temp",
    "System Temp",
    "FAN",
    "MB",
    "PS",
    "DBP",
    "SYS"
]
# Create a metric to track time spent and requests made.
REQUEST_TIME = Summary('request_processing_seconds', 'Time spent processing request')


def _run_cmd(ip, raw):
    logging.info("Collecting from target %s", ip)
    proc = subprocess.Popen(["ipmitool",
                             "-H", ip,
                             "-U", IPMI_USER,
                             "-P", IPMI_PASSWD,
                             "-L", IPMI_PRIV,
                             "sdr"], stdout=subprocess.PIPE)
    out = proc.communicate()[0]
    raw += [x.rstrip() for x in out.split('|')]


class IpmiCollector(object):
    @REQUEST_TIME.time()
    def collect(self):
        sys_metrics = {
            'cpu_temp': GaugeMetricFamily('ipmi_cpu_temp', 'CPU temp', labels=['ip']),
            'system_temp': GaugeMetricFamily('ipmi_system_temp', 'System temp', labels=['ip']),
            'fan_speed': GaugeMetricFamily('ipmi_fan_speed', 'Fan speed', labels=['ip']),
            'power': GaugeMetricFamily('ipmi_power', 'power', labels=['ip'])
        }
        raw = Manager().list([])
        for ip in IPS:
            # This is an attempt to run the `ipmi` tool in parallel
            # to avoid timeouts in Prometheus
            p = Process(target=_run_cmd, args=(ip, raw))
            logging.info("Start collecting the metrics")
            p.start()
            p.join()
            all_metrics = dict(itertools.izip_longest(*[iter(raw)] * 2, fillvalue=""))
            for k, v in all_metrics.items():
                for r in REQURED:
                    if r in k:
                        print("V:",v,"K:",k)
                        ff = re.search('\d{1,3}\.\d{2}', v)
                        if v in SKIP_PARAM:
                            continue
                        if ff is not None:
                            value = float(ff.group())
                        else:
                            #value = [int(s,0) for s in v.split() if s.isdigit()][0]
                            value = [int(s, 0) for s in v.split() if (s.isdigit()  )][0]
                        if 'CPU' in k:
                            sys_metrics['cpu_temp'].add_metric([ip+k], value)
                        elif 'System' in k or 'T_AMB' in k or 'T_OUT' in k:
                            sys_metrics['system_temp'].add_metric([ip+k], value)
                        elif 'FAN' in k:
                            sys_metrics['fan_speed'].add_metric([ip+k], value)
                        elif 'PS' in k:
                            sys_metrics['power'].add_metric([ip+k], value)
                        else:
                            logging.error("Undefined metric: %s", k)

        for metric in sys_metrics.values():
            yield metric


def main():
    REGISTRY.register(IpmiCollector())
    start_http_server(8001)
    while True:
        time.sleep(5)

if __name__ == "__main__":
    logging.basicConfig(format='ts=%(asctime)s level=%(levelname)s msg=%(message)s', level=logging.DEBUG)
    main()
