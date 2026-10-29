{
  description = "labeltree-db development environment";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs = { self, nixpkgs }:
    let
      systems = [ "x86_64-linux" "aarch64-linux" "x86_64-darwin" "aarch64-darwin" ];
      forAllSystems = f: nixpkgs.lib.genAttrs systems (system: f nixpkgs.legacyPackages.${system});
    in
    {
      devShells = forAllSystems (pkgs:
        let
          python = pkgs.python314;
          postgresql = pkgs.postgresql_18;

          # Local PostgreSQL in ./.pgdata, reachable only via a unix socket in that directory.
          db-start = pkgs.writeShellApplication {
            name = "db-start";
            runtimeInputs = [ postgresql ];
            text = ''
              if [ ! -f "$PGDATA/PG_VERSION" ]; then
                initdb --pgdata="$PGDATA" --username="$PGUSER" --auth=trust \
                  --encoding=UTF8 --no-locale >/dev/null
                fresh=1
              fi
              if pg_ctl status --pgdata="$PGDATA" >/dev/null; then
                echo "postgres already running ($PGDATA)"
              else
                pg_ctl start --pgdata="$PGDATA" --log="$PGDATA/postgres.log" --wait \
                  -o "-c listen_addresses=''' -c unix_socket_directories='$PGDATA' -p $PGPORT"
              fi
              if [ -n "''${fresh:-}" ]; then
                createdb "$PGDATABASE"
              fi
            '';
          };

          db-stop = pkgs.writeShellApplication {
            name = "db-stop";
            runtimeInputs = [ postgresql ];
            text = ''pg_ctl stop --pgdata="$PGDATA" --mode=fast'';
          };

          # Postgres plus Django's runserver in the background (own process group,
          # so app-stop also ends the autoreloader's child). State lives in ./.run.
          app-start = pkgs.writeShellApplication {
            name = "app-start";
            runtimeInputs = [ db-start pkgs.util-linux ];
            text = ''
              : "''${PROJECT_ROOT:?run inside nix develop}"
              run="$PROJECT_ROOT/.run"
              pidfile="$run/runserver.pid"
              port="''${APP_PORT:-8000}"
              db-start
              if [ -f "$pidfile" ] && kill -0 "$(cat "$pidfile")" 2>/dev/null; then
                echo "runserver already running (pid $(cat "$pidfile"))"
                exit 0
              fi
              mkdir -p "$run"
              cd "$PROJECT_ROOT/src"
              setsid "$PROJECT_ROOT/.venv/bin/python" manage.py runserver "0.0.0.0:$port" \
                >"$run/runserver.log" 2>&1 </dev/null &
              echo $! >"$pidfile"
              echo "runserver started: http://localhost:$port/api/v1/docs (log: .run/runserver.log)"
            '';
          };

          app-stop = pkgs.writeShellApplication {
            name = "app-stop";
            runtimeInputs = [ db-stop postgresql ];
            text = ''
              : "''${PROJECT_ROOT:?run inside nix develop}"
              pidfile="$PROJECT_ROOT/.run/runserver.pid"
              if [ -f "$pidfile" ] && kill -0 "$(cat "$pidfile")" 2>/dev/null; then
                kill -- -"$(cat "$pidfile")"
                echo "runserver stopped"
              else
                echo "runserver not running"
              fi
              rm -f "$pidfile"
              if pg_ctl status --pgdata="$PGDATA" >/dev/null; then
                db-stop
              else
                echo "postgres not running"
              fi
            '';
          };
        in
        {
          default = pkgs.mkShell {
            # nodejs runs the web app's expander tests (node --test); Playwright's
            # browsers come from nixpkgs, matching the pinned Python playwright.
            packages = [
              python postgresql pkgs.ruff pkgs.nodejs db-start db-stop app-start app-stop
            ];

            PLAYWRIGHT_BROWSERS_PATH = "${pkgs.playwright-driver.browsers}";
            PLAYWRIGHT_SKIP_VALIDATE_HOST_REQUIREMENTS = "true";
            # The pip wheel's bundled node can't run on NixOS; use nixpkgs' node instead.
            PLAYWRIGHT_NODEJS_PATH = "${pkgs.nodejs}/bin/node";
            # pip wheels with C++ extensions (greenlet, used by playwright) need libstdc++.
            LD_LIBRARY_PATH = pkgs.lib.makeLibraryPath [ pkgs.stdenv.cc.cc.lib ];

            shellHook = ''
              # Anchor to the repo root even when entered from a subdirectory (e.g. src/).
              PROJECT_ROOT="$PWD"
              while [ ! -f "$PROJECT_ROOT/flake.nix" ] && [ "$PROJECT_ROOT" != / ]; do
                PROJECT_ROOT="$(dirname "$PROJECT_ROOT")"
              done
              export PROJECT_ROOT

              set -a
              [ -f "$PROJECT_ROOT/.env" ] && . "$PROJECT_ROOT/.env"
              set +a

              export PGDATA="$PROJECT_ROOT/.pgdata"
              export POSTGRES_HOST="''${POSTGRES_HOST:-$PGDATA}"
              export POSTGRES_PORT="''${POSTGRES_PORT:-5432}"
              export PGHOST="$POSTGRES_HOST" PGPORT="$POSTGRES_PORT"
              export PGUSER="''${POSTGRES_USER:-labeltree}" PGDATABASE="''${POSTGRES_DB:-labeltree}"

              if [ ! -d "$PROJECT_ROOT/.venv" ]; then
                ${python}/bin/python -m venv "$PROJECT_ROOT/.venv"
                echo "Created .venv; run: pip install -e '$PROJECT_ROOT[dev]'"
              fi
              . "$PROJECT_ROOT/.venv/bin/activate"
            '';
          };
        });
    };
}
