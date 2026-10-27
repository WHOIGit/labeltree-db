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
        in
        {
          default = pkgs.mkShell {
            packages = [ python postgresql pkgs.ruff db-start db-stop ];

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
