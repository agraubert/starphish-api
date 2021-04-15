import argparse
import sys
from getpass import getuser

TEMPLATE = """[Unit]
Description={description}
After={after}
StartLimitIntervalSec=60

[Service]
Type=simple
Restart=always
RestartSec=1
User={user}
ExecStart={exec} {path}
{environment}

[Install]
WantedBy=multi-user.target
"""

if __name__ == '__main__':
    parser = argparse.ArgumentParser('starphish-service')

    parser.add_argument('name', help='Service name')
    parser.add_argument('id', help='Service id')
    parser.add_argument('path', help='Path to the program')
    parser.add_argument('-e', '--env', nargs=2, metavar=('KEY', 'VAL'), action='append', default=None)
    parser.add_argument('-u', '--user', default=getuser())
    parser.add_argument('-a', '--after', default='network.target')

    args = parser.parse_args()

    service = TEMPLATE.format(
        description=args.name,
        path=args.path,
        user=args.user,
        after=args.after,
        exec=sys.executable,
        environment='' if args.env is None else (
            '\n'.join(
                'Environment="{}={}"'.format(k,v)
                for k,v in args.env
            )
        )
    )

    print(service)
