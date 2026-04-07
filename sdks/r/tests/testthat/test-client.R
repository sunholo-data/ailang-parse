test_that("DocParse$new resolves api_key from env when no arg given", {
  withr::with_envvar(
    list(DOCPARSE_API_KEY = "dp_env_key", XDG_CONFIG_HOME = tempfile()),
    {
      client <- DocParse$new()
      expect_equal(client$api_key, "dp_env_key")
      expect_equal(client$base_url, "https://docparse.ailang.sunholo.com")
      expect_s3_class(client$keys, "KeyManager")
    }
  )
})

test_that("DocParse$new prefers explicit key over env", {
  withr::with_envvar(
    list(DOCPARSE_API_KEY = "dp_env"),
    {
      client <- DocParse$new(api_key = "dp_explicit")
      expect_equal(client$api_key, "dp_explicit")
    }
  )
})

test_that("DocParse$new strips trailing slash from base_url", {
  client <- DocParse$new(api_key = "dp_x",
                         base_url = "https://example.com/")
  expect_equal(client$base_url, "https://example.com")
})

test_that("parse pipeline (unwrap + result) handles a realistic envelope", {
  inner <- list(
    status   = "success",
    filename = "report.docx",
    format   = "zip-office",
    blocks   = list(
      list(type = "heading", text = "Q1", level = 1L),
      list(type = "text",    text = "summary line")
    ),
    metadata = list(title = "Q1", author = "Mark", pageCount = 5L),
    summary  = list(totalBlocks = 2L, headings = 1L)
  )
  inner_str <- as.character(jsonlite::toJSON(inner, auto_unbox = TRUE))
  envelope_text <- as.character(
    jsonlite::toJSON(list(result = inner_str), auto_unbox = TRUE)
  )
  res <- ailangparse:::.parse_result_from_list(
    ailangparse:::.unwrap(envelope_text)
  )
  expect_s3_class(res, "ailang_parse_result")
  expect_equal(res$status, "success")
  expect_equal(res$filename, "report.docx")
  expect_length(res$blocks, 2L)
  expect_s3_class(res$blocks[[1]], "ailang_block_heading")
  expect_equal(res$metadata$title, "Q1")
  expect_equal(res$metadata$page_count, 5L)
  expect_equal(res$summary$total_blocks, 2L)
})

test_that("UnstructuredClient picks up env api_key", {
  withr::with_envvar(
    list(DOCPARSE_API_KEY = "dp_us", XDG_CONFIG_HOME = tempfile()),
    {
      uc <- UnstructuredClient$new()
      expect_equal(uc$api_key, "dp_us")
      expect_equal(uc$server_url, "https://docparse.ailang.sunholo.com")
    }
  )
})
