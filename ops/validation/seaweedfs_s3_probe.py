"""Owner-run S3 probe; no cluster access at import, no private output."""
import argparse
from contextlib import contextmanager
import datetime
import hashlib
import hmac
import http.client
import json
from pathlib import Path
import re
import socket
import subprocess
import time
import urllib.parse
import uuid


class GateError(Exception):
    """Only fixed, non-private gate identifiers may be passed here."""


def require(condition, gate):
    if not condition:
        raise GateError(gate)


def load_config(path):
    cfg = json.loads(path.read_text(encoding='utf-8-sig'))
    require(cfg.get('schemaVersion') == 1 and cfg.get('provider') == 'seaweedfs'
            and cfg.get('chartVersion') == '4.45.0', 'invalid_config_version')
    buckets = cfg.get('buckets')
    require(isinstance(buckets, list) and bool(buckets), 'invalid_buckets')
    for bucket in buckets:
        require(isinstance(bucket, str) and
                re.fullmatch(r'[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]', bucket)
                and '..' not in bucket and '.-' not in bucket and '-.' not in bucket
                and not re.fullmatch(r'\d+\.\d+\.\d+\.\d+', bucket), 'invalid_bucket')
    require(len(set(buckets)) == len(buckets), 'duplicate_buckets')
    credentials = []
    for field in ('accessKeyFile', 'secretKeyFile'):
        file = Path(cfg[field])
        require(file.is_absolute() and file.is_file(), 'invalid_credential_file')
        value = file.read_text(encoding='utf-8-sig').strip()
        require(bool(value) and not any(c.isspace() for c in value), 'invalid_credential')
        credentials.append(value)
    return buckets, credentials


class Client:
    def __init__(self, port, access, secret):
        self.port, self.access, self.secret = port, access, secret

    def request(self, method, path, body=b'', mode='signed', query=''):
        now = datetime.datetime.now(datetime.timezone.utc)
        stamp, day = now.strftime('%Y%m%dT%H%M%SZ'), now.strftime('%Y%m%d')
        digest = hashlib.sha256(body).hexdigest()
        uri = urllib.parse.quote(path, safe='/~')
        host = f'127.0.0.1:{self.port}'
        headers = {'Host': host, 'x-amz-date': stamp, 'x-amz-content-sha256': digest}
        if mode != 'anonymous':
            names = 'host;x-amz-content-sha256;x-amz-date'
            canonical = (f'{method}\n{uri}\n{query}\nhost:{host}\n'
                         f'x-amz-content-sha256:{digest}\nx-amz-date:{stamp}\n\n{names}\n{digest}')
            scope = f'{day}/us-east-1/s3/aws4_request'
            string = f'AWS4-HMAC-SHA256\n{stamp}\n{scope}\n{hashlib.sha256(canonical.encode()).hexdigest()}'
            key = ('AWS4' + self.secret).encode()
            for part in (day, 'us-east-1', 's3', 'aws4_request'):
                key = hmac.new(key, part.encode(), hashlib.sha256).digest()
            signature = hmac.new(key, string.encode(), hashlib.sha256).hexdigest()
            identity = self.access if mode == 'signed' else 'invalid-probe-credential'
            headers['Authorization'] = (f'AWS4-HMAC-SHA256 Credential={identity}/{scope}, '
                                        f'SignedHeaders={names}, Signature={signature}')
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=20)
        try:
            conn.request(method, uri + ('?' + query if query else ''), body=body, headers=headers)
            response = conn.getresponse()
            data = response.read(2 * 1024 * 1024 + 1)
            require(len(data) <= 2 * 1024 * 1024, 'response_too_large')
            return response.status, data
        finally:
            conn.close()


@contextmanager
def tunnel(port, context):
    with socket.socket() as test:
        test.bind(('127.0.0.1', port))
    command = ['kubectl', '--context', context, '-n', 'faang-object-storage',
               'port-forward', 'service/faang-object-storage-seaweedfs-s3',
               f'{port}:9000', '--address=127.0.0.1']
    process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(30):
            require(process.poll() is None, 'port_forward_failed')
            try:
                with socket.create_connection(('127.0.0.1', port), timeout=1):
                    break
            except OSError:
                time.sleep(0.5)
        else:
            raise GateError('port_forward_timeout')
        yield
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def probe(client, buckets, create_buckets=False, test_objects=False):
    passed = True
    for index, bucket in enumerate(buckets, 1):
        path = '/' + bucket
        status, _ = client.request('GET', path, query='list-type=2&max-keys=1')
        print(f'bucket_{index}_authenticated_list_http={status}', flush=True)
        if status == 404 and create_buckets:
            status, _ = client.request('PUT', path)
            require(status in (200, 204), 'bucket_provisioning_denied')
            status, _ = client.request('GET', path, query='list-type=2&max-keys=1')
        passed = passed and status == 200
        for mode in ('anonymous', 'invalid'):
            denied, _ = client.request('GET', path, mode=mode, query='list-type=2&max-keys=1')
            print(f'bucket_{index}_{mode}_http={denied}', flush=True)
            require(denied in (401, 403), 'unauthorized_access_not_denied')
        if test_objects:
            require(status == 200, 'bucket_not_ready')
            key = path + '/delivery-probe/' + uuid.uuid4().hex + '.bin'
            require(client.request('HEAD', key)[0] == 404, 'probe_key_collision_or_access_error')
            payload = b'faang-seaweedfs-delivery-proof-v1\n' * 4096
            expected = hashlib.sha256(payload).hexdigest()
            # Attempt cleanup even if a successful server write loses its response.
            try:
                require(client.request('PUT', key, payload)[0] == 200, 'probe_put_failed')
                code, data = client.request('GET', key)
                require(code == 200 and hashlib.sha256(data).hexdigest() == expected,
                        'probe_checksum_failed')
                print(f'bucket_{index}_put_get_checksum={expected}', flush=True)
            finally:
                require(client.request('DELETE', key)[0] in (200, 204), 'probe_cleanup_failed')
                require(client.request('HEAD', key)[0] == 404, 'probe_cleanup_not_confirmed')
                print(f'bucket_{index}_probe_cleanup=passed', flush=True)
    require(passed, 'required_bucket_unavailable')


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument('--config', type=Path, default=Path(__file__).resolve().parents[2]
                        / 'config/seaweedfs-app-s3.local.json')
    result.add_argument('--context', required=True, help='Reviewed kubectl context (not printed)')
    result.add_argument('--port', type=int, default=18973)
    modes = result.add_mutually_exclusive_group()
    modes.add_argument('--create-buckets', action='store_true', help='Owner-approved bucket bootstrap only')
    modes.add_argument('--test-objects', action='store_true', help='Owner-approved disposable object test')
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        require(1024 <= args.port <= 65535, 'invalid_port')
        buckets, credentials = load_config(args.config)
        with tunnel(args.port, args.context):
            probe(Client(args.port, *credentials), buckets, args.create_buckets, args.test_objects)
        print('probe=passed', flush=True)
        return 0
    except Exception as exc:
        print('probe=failed gate=' + (str(exc) if isinstance(exc, GateError)
                                      else type(exc).__name__), flush=True)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
