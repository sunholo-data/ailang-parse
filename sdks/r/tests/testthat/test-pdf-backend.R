## pdf_backend on the parse entry points, and uploads over the hosting
## platform's 32 MiB request cap (FILE_TOO_LARGE).

.ok_parse_resp <- function() {
  inner <- list(status = "ok", filename = "doc.pdf", format = "pdf",
                blocks = list(), metadata = setNames(list(), character()),
                summary = list(totalBlocks = 0L))
  httr2::response(
    status_code = 200L,
    headers = list("content-type" = "application/json"),
    body = charToRaw(jsonlite::toJSON(
      list(result = as.character(jsonlite::toJSON(inner, auto_unbox = TRUE))),
      auto_unbox = TRUE))
  )
}

# Mock that records each request and answers with an empty parse.
.recorder <- function() {
  env <- new.env()
  env$reqs <- list()
  env$mock <- function(req) {
    env$reqs[[length(env$reqs) + 1L]] <- req
    .ok_parse_resp()
  }
  env
}

.body_field <- function(req, name) {
  v <- req$body$data[[name]]
  if (is.null(v)) NULL else as.character(v)
}

.tmp_file <- function(bytes, ext = ".pdf") {
  p <- tempfile(fileext = ext)
  writeBin(bytes, p)
  p
}

# ── pdf_backend ──

test_that("parse() sends pdfBackend and gcsRef", {
  rec <- .recorder()
  httr2::with_mocked_responses(rec$mock, {
    DocParse$new(api_key = "dp_test")$parse(
      "", pdf_backend = "ai", gcs_ref = "gs://b/big.pdf")
  })
  expect_equal(.body_field(rec$reqs[[1]], "pdfBackend"), "ai")
  expect_equal(.body_field(rec$reqs[[1]], "gcsRef"), "gs://b/big.pdf")
})

test_that("parse() omits pdfBackend by default", {
  rec <- .recorder()
  httr2::with_mocked_responses(rec$mock, {
    DocParse$new(api_key = "dp_test")$parse("sample_pdf")
  })
  expect_null(.body_field(rec$reqs[[1]], "pdfBackend"))
  expect_null(.body_field(rec$reqs[[1]], "gcsRef"))
})

test_that("parse_url() sends pdfBackend", {
  rec <- .recorder()
  httr2::with_mocked_responses(rec$mock, {
    DocParse$new(api_key = "dp_test")$parse_url(
      "https://example.com/scan.pdf", pdf_backend = "poppler")
  })
  expect_equal(.body_field(rec$reqs[[1]], "pdfBackend"), "poppler")
  expect_equal(.body_field(rec$reqs[[1]], "sourceUrl"),
               "https://example.com/scan.pdf")
})

test_that("parse_file() sends pdfBackend as a form field", {
  local <- .tmp_file(charToRaw("%PDF-1.4"))
  on.exit(unlink(local))
  rec <- .recorder()
  httr2::with_mocked_responses(rec$mock, {
    DocParse$new(api_key = "dp_test")$parse_file(local, pdf_backend = "ai")
  })
  expect_equal(.body_field(rec$reqs[[1]], "pdfBackend"), "ai")
})

test_that("parse_file() omits pdfBackend by default", {
  local <- .tmp_file(charToRaw("%PDF-1.4"))
  on.exit(unlink(local))
  rec <- .recorder()
  httr2::with_mocked_responses(rec$mock, {
    DocParse$new(api_key = "dp_test")$parse_file(local)
  })
  expect_null(.body_field(rec$reqs[[1]], "pdfBackend"))
})

# ── FILE_TOO_LARGE ──

test_that("parse_file() over 32 MiB stops before sending", {
  big <- .tmp_file(raw(33554432 + 1))
  on.exit(unlink(big))
  rec <- .recorder()
  err <- httr2::with_mocked_responses(rec$mock, {
    tryCatch(DocParse$new(api_key = "dp_test")$parse_file(big),
             ailang_docparse_error = function(e) e)
  })
  expect_s3_class(err, "ailang_docparse_error")
  expect_equal(err$code, "FILE_TOO_LARGE")
  expect_equal(err$status_code, 413L)
  expect_equal(err$details$size_bytes, 33554433)
  expect_match(conditionMessage(err), "parse_url", fixed = TRUE)
  expect_match(conditionMessage(err), "/api/v1/upload/url", fixed = TRUE)
  expect_length(rec$reqs, 0L)
})

test_that("parse_file() at exactly 32 MiB is sent", {
  ok <- .tmp_file(raw(33554432))
  on.exit(unlink(ok))
  rec <- .recorder()
  httr2::with_mocked_responses(rec$mock, {
    DocParse$new(api_key = "dp_test")$parse_file(ok)
  })
  expect_length(rec$reqs, 1L)
})

test_that("HTML 413 from the front end becomes FILE_TOO_LARGE", {
  local <- .tmp_file(charToRaw("%PDF-1.4"))
  on.exit(unlink(local))
  page <- httr2::response(
    status_code = 413L,
    headers = list("content-type" = "text/html; charset=UTF-8"),
    body = charToRaw(paste0("<!DOCTYPE html><html><title>Error 413 ",
                            "(Request Entity Too Large)!!1</title></html>"))
  )
  err <- httr2::with_mocked_responses(list(page), {
    tryCatch(DocParse$new(api_key = "dp_test")$parse_file(local),
             ailang_docparse_error = function(e) e)
  })
  expect_equal(err$code, "FILE_TOO_LARGE")
  expect_equal(err$status_code, 413L)
  expect_false(grepl("<html", conditionMessage(err), ignore.case = TRUE))
})

test_that("JSON 413 from the API keeps its own code", {
  resp <- httr2::response(
    status_code = 413L,
    headers = list("content-type" = "application/json"),
    body = charToRaw(jsonlite::toJSON(list(error = list(
      code = "FILE_TOO_LARGE",
      message = "File exceeds your tier limit (10 MB)")), auto_unbox = TRUE))
  )
  err <- httr2::with_mocked_responses(list(resp), {
    tryCatch(DocParse$new(api_key = "dp_test")$parse("sample_pdf"),
             ailang_docparse_error = function(e) e)
  })
  expect_equal(err$code, "FILE_TOO_LARGE")
  expect_match(conditionMessage(err), "tier limit", fixed = TRUE)
})

test_that("structured envelope code is exposed", {
  json <- as.character(jsonlite::toJSON(list(
    error = list(code = "FILE_TOO_LARGE", message = "too big"),
    request_id = "r1"), auto_unbox = TRUE))
  err <- tryCatch(ailangparse:::.unwrap(json),
                  ailang_docparse_error = function(e) e)
  expect_equal(err$code, "FILE_TOO_LARGE")
  expect_equal(err$request_id, "r1")
})
