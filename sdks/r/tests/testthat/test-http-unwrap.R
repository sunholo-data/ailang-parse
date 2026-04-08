.envelope <- function(inner) {
  inner_str <- as.character(jsonlite::toJSON(inner, auto_unbox = TRUE))
  as.character(jsonlite::toJSON(list(result = inner_str), auto_unbox = TRUE))
}

test_that("unwrap returns inner JSON object on success", {
  out <- ailangparse:::.unwrap(.envelope(list(status = "ok", filename = "x.docx")))
  expect_equal(out$status, "ok")
  expect_equal(out$filename, "x.docx")
})

test_that("unwrap raises docparse_error on string error envelope", {
  expect_error(
    ailangparse:::.unwrap('{"error": "boom"}'),
    class = "ailang_docparse_error",
    regexp = "boom"
  )
})

test_that("unwrap raises docparse_error on inner result error", {
  expect_error(
    ailangparse:::.unwrap(.envelope(list(error = list(message = "inner failure")))),
    class = "ailang_docparse_error",
    regexp = "inner failure"
  )
})

test_that("unwrap routes 'Invalid or expired API key' envelope to auth_error", {
  expect_error(
    ailangparse:::.unwrap('{"error": "Invalid or expired API key"}'),
    class = "ailang_auth_error"
  )
})

test_that("unwrap routes inner-result auth error to auth_error", {
  expect_error(
    ailangparse:::.unwrap(.envelope(list(error = list(message = "Invalid or expired API key")))),
    class = "ailang_auth_error"
  )
})

test_that("unwrap routes 'Unauthorized' envelope to auth_error", {
  expect_error(
    ailangparse:::.unwrap('{"error": "Unauthorized"}'),
    class = "ailang_auth_error"
  )
})

test_that("unwrap leaves non-auth envelope errors as plain docparse_error", {
  err <- tryCatch(
    ailangparse:::.unwrap('{"error": "malformed document"}'),
    error = function(e) e
  )
  expect_s3_class(err, "ailang_docparse_error")
  expect_false(inherits(err, "ailang_auth_error"))
})

test_that("stop_for_status maps 401/429 to typed errors", {
  expect_error(ailangparse:::.stop_for_status(401L, ""),
               class = "ailang_auth_error")
  expect_error(ailangparse:::.stop_for_status(429L, ""),
               class = "ailang_quota_error")
  expect_error(ailangparse:::.stop_for_status(500L, "boom"),
               class = "ailang_docparse_error",
               regexp = "500")
})
