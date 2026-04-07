test_that("live parse against hosted API (DOCPARSE_API_KEY required)", {
  key <- Sys.getenv("DOCPARSE_API_KEY", unset = "")
  skip_if(!nzchar(key), "DOCPARSE_API_KEY not set; skipping integration test")
  skip_on_cran()

  client <- DocParse$new()
  health <- client$health()
  expect_equal(health$status, "ok")

  formats <- client$formats()
  expect_true("docx" %in% formats$parse)
})
