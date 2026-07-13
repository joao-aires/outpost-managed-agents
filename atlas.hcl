data "external_schema" "sqlalchemy" {
  program = [
    "atlas-provider-sqlalchemy",
    "--path", "./app/models_loader.py",
    "--dialect", "postgresql"
  ]
}

env "local" {
  src = data.external_schema.sqlalchemy.url
  dev = "docker://postgres/15-alpine/dev" # Atlas uses a temporary docker DB to perform diffs
  
  migration {
    dir = "file://migrations"
  }
}
