#' AILANG Parse error conditions
#'
#' All errors raised by the SDK have class
#' \code{c("ailang_docparse_error", "error", "condition")}. Auth and quota
#' failures additionally carry \code{ailang_auth_error} and
#' \code{ailang_quota_error}, so callers can dispatch with
#' \code{tryCatch(ailang_quota_error = ...)}.
#'
#' Every error carries \code{code}: the machine-readable code from the API's
#' structured error envelope (e.g. \code{"FILE_TOO_LARGE"}), or \code{""}.
#'
#' @keywords internal
#' @name errors
NULL

.docparse_error <- function(message, status_code = 0L, suggested_fix = "",
                            details = NULL, request_id = "", code = "", ...,
                            class = character()) {
  structure(
    class = c(class, "ailang_docparse_error", "error", "condition"),
    list(message = message, call = NULL, status_code = status_code,
         suggested_fix = suggested_fix, details = details,
         request_id = request_id, code = code, ...)
  )
}

.auth_error <- function(message = "Invalid or missing API key", code = "") {
  .docparse_error(message, status_code = 401L, code = code,
                  class = "ailang_auth_error")
}

# Largest request body the hosting platform (Cloud Run, HTTP/1) accepts:
# 32 MiB. A direct multipart upload above it never reaches the API, on any
# tier.
.MAX_DIRECT_UPLOAD_BYTES <- 33554432

.LARGE_FILE_ROUTES <- paste0(
  "For larger files, pass a signed or public https URL with $parse_url() ",
  "(or source_url =); the server fetches it, up to your tier's file-size ",
  "limit. On Business, POST /api/v1/upload/url, PUT the file to the ",
  "returned upload_url, then pass its gcs_ref to $parse(gcs_ref = ...)."
)

# The structured error for an upload over the platform's request cap.
# size_bytes is NULL when the SDK did not measure the upload: a 413 page
# that came back from the hosting platform's front end.
.file_too_large_error <- function(size_bytes = NULL) {
  lead <- if (is.null(size_bytes)) {
    "Upload rejected by the hosting platform (HTTP 413)."
  } else {
    sprintf("File is %.0f bytes.", size_bytes)
  }
  details <- list(limit_bytes = .MAX_DIRECT_UPLOAD_BYTES)
  if (!is.null(size_bytes)) details$size_bytes <- size_bytes
  .docparse_error(
    sprintf(paste0("%s Direct uploads are limited to 32 MiB (%.0f bytes) by ",
                   "the hosting platform on every tier. %s"),
            lead, .MAX_DIRECT_UPLOAD_BYTES, .LARGE_FILE_ROUTES),
    status_code = 413L,
    suggested_fix = .LARGE_FILE_ROUTES,
    details = details,
    code = "FILE_TOO_LARGE"
  )
}

# Stop with FILE_TOO_LARGE, before anything is sent, when the files of a
# multipart upload exceed the platform's request cap together.
.check_upload_size <- function(paths) {
  paths <- paths[!vapply(paths, is.null, logical(1))]
  total <- sum(vapply(paths, function(p) as.numeric(file.size(p)), numeric(1)))
  if (isTRUE(total > .MAX_DIRECT_UPLOAD_BYTES)) {
    stop(.file_too_large_error(total))
  }
  invisible(total)
}

.quota_error <- function(message = "Quota exceeded",
                         tier = "", used = 0L, limit = 0L) {
  .docparse_error(
    message,
    status_code = 429L,
    tier = tier, used = used, limit = limit,
    class = "ailang_quota_error"
  )
}

.stop_for_status <- function(status_code, body_text = "") {
  if (status_code == 401L) stop(.auth_error())
  if (status_code == 429L) {
    info <- tryCatch(jsonlite::fromJSON(body_text), error = function(e) NULL)
    tier  <- if (is.list(info) && !is.null(info$tier))  info$tier  else ""
    used  <- if (is.list(info) && !is.null(info$used))  info$used  else 0L
    limit <- if (is.list(info) && !is.null(info$limit)) info$limit else 0L
    stop(.quota_error(tier = tier, used = used, limit = limit))
  }
  is_json <- nzchar(body_text) && isTRUE(jsonlite::validate(body_text))
  if (status_code == 413L && !is_json) {
    # The hosting platform's front end, not the API: an HTML page for a
    # request over its 32 MiB cap.
    stop(.file_too_large_error())
  }
  if (status_code >= 400L) {
    snippet <- substr(body_text, 1L, 200L)
    code <- ""
    if (is_json) {
      info <- tryCatch(jsonlite::fromJSON(body_text, simplifyVector = FALSE),
                       error = function(e) NULL)
      if (is.list(info) && is.list(info$error) && !is.null(info$error$code)) {
        code <- as.character(info$error$code)
      }
    }
    stop(.docparse_error(
      sprintf("API error: %d %s", status_code, snippet),
      status_code = status_code,
      code = code
    ))
  }
}
