test_that("save_key + load_saved_key round-trip", {
  skip_on_cran()
  tmp <- tempfile("xdg-")
  dir.create(tmp)
  withr::with_envvar(
    list(XDG_CONFIG_HOME = tmp, APPDATA = tmp, DOCPARSE_API_KEY = NA_character_),
    {
      save_key(
        api_key  = "dp_test_round_trip",
        base_url = "https://docparse.ailang.sunholo.com",
        key_id   = "key-1",
        tier     = "free",
        label    = "test"
      )
      path <- credentials_path()
      expect_true(file.exists(path))

      loaded <- load_saved_key("https://docparse.ailang.sunholo.com")
      expect_false(is.null(loaded))
      expect_equal(loaded$api_key, "dp_test_round_trip")
      expect_equal(loaded$key_id,  "key-1")
      expect_equal(loaded$tier,    "free")
      expect_equal(loaded$label,   "test")

      # base_url filtering: a different URL must not match
      expect_null(load_saved_key("https://other.example.com"))
    }
  )
})

test_that("resolve_api_key honours DOCPARSE_API_KEY first", {
  withr::with_envvar(
    list(DOCPARSE_API_KEY = "dp_from_env"),
    expect_equal(resolve_api_key(), "dp_from_env")
  )
})

test_that("resolve_api_key falls back to saved file with no base_url filter", {
  skip_on_cran()
  tmp <- tempfile("xdg-")
  dir.create(tmp)
  withr::with_envvar(
    list(XDG_CONFIG_HOME = tmp, APPDATA = tmp, DOCPARSE_API_KEY = NA_character_),
    {
      save_key("dp_saved_only", base_url = "https://other.example.com")
      expect_equal(resolve_api_key(), "dp_saved_only")
    }
  )
})

test_that("load_saved_key returns NULL when key has no dp_ prefix", {
  skip_on_cran()
  tmp <- tempfile("xdg-")
  dir.create(tmp)
  withr::with_envvar(
    list(XDG_CONFIG_HOME = tmp, APPDATA = tmp),
    {
      d <- file.path(tmp, "ailang-parse")
      dir.create(d, recursive = TRUE)
      writeLines(
        jsonlite::toJSON(list(api_key = jsonlite::unbox("not_prefixed"))),
        file.path(d, "credentials.json")
      )
      expect_null(load_saved_key())
    }
  )
})
