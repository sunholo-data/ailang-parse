test_that("live parse against hosted API (DOCPARSE_API_KEY required)", {
  key <- Sys.getenv("DOCPARSE_API_KEY", unset = "")
  skip_if(!nzchar(key), "DOCPARSE_API_KEY not set; skipping integration test")
  skip_on_cran()

  client <- DocParse$new()
  health <- client$health()
  # The hosted API answers "healthy"; older deployments answered "ok". The
  # Python and JS suites already accept either — this one did not, and failed
  # against live infrastructure that was working correctly.
  expect_true(health$status %in% c("ok", "healthy"))

  formats <- client$formats()
  expect_true("docx" %in% formats$parse)
})
