{ pkgs }: {
  deps = [
    # Python
    pkgs.python310
    pkgs.python310Packages.pip
    pkgs.python310Packages.virtualenv

    # Node.js for n8n and front-end tooling
    pkgs.nodejs_20
    pkgs.yarn

    # Infrastructure tools
    pkgs.terraform
    pkgs.ansible
    pkgs.curl
    pkgs.jq
    pkgs.yq

    # Database and caching
    pkgs.postgresql_15
    pkgs.redis

    # OPA for policy evaluation
    pkgs.opa

    # Observability
    pkgs.grafana

    # Container runtime
    pkgs.docker
    pkgs.docker-compose

    # Make and build tools
    pkgs.gnumake
    pkgs.pkg-config

    # Git
    pkgs.git

    # Essential utilities
    pkgs.wget
    pkgs.vim
    pkgs.tmux
  ];

  env = {
    PYTHONUNBUFFERED = "1";
    PYTHONPATH = "/home/runner/${REPL_SLUG}";
    LD_LIBRARY_PATH = "${pkgs.lib.makeLibraryPath [pkgs.libpq pkgs.openssl]}:$LD_LIBRARY_PATH";
  };

  # Shell initialization
  shell.hook = ''
    if [ ! -f .venv/bin/activate ]; then
      python3 -m venv .venv
    fi
    source .venv/bin/activate
    pip install -q -r requirements.txt || true
  '';
}
