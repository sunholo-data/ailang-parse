#' AILANG Parse error conditions
#'
#' All errors raised by the SDK have class
#' \code{c("ailang_docparse_error", "error", "condition")}. Auth and quota
#' failures additionally carry \code{ailang_auth_error} and
#' \code{ailang_quota_error}, so callers can dispatch with
#' \code{tryCatch(ailang_quota_error = ...)}.
#'
#' @keywords internal
#' @name errors
NULL

.docparse_error <- function(message, status_code = 0L, suggested_fix = "",
                            details = NULL, request_id = "", ..., class = character()) {
  structure(
    class = c(class, "ailang_docparse_error", "error", "condition"),
    list(message = message, call = NULL, status_code = status_code,
         suggested_fix = suggested_fix, details = details,
         request_id = request_id, ...)
  )
}

.auth_error <- function(message = "Invalid or missing API key") {
  .docparse_error(message, status_code = 401L, class = "ailang_auth_error")
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
  if (status_code >= 400L) {
    snippet <- substr(body_text, 1L, 200L)
    stop(.docparse_error(
      sprintf("API error: %d %s", status_code, snippet),
      status_code = status_code
    ))
  }
}
