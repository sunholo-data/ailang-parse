#' Internal HTTP helpers
#'
#' Thin wrapper around \pkg{httr2} that handles the AILANG Parse serve-API
#' response envelope (a JSON object with either a \code{result} field whose
#' value is a JSON-encoded string, or an \code{error} field).
#'
#' @keywords internal
#' @name http
NULL

.build_request <- function(base_url, path, api_key = NULL, timeout = 60) {
  req <- httr2::request(paste0(sub("/$", "", base_url), path))
  req <- httr2::req_timeout(req, timeout)
  req <- httr2::req_user_agent(req, "ailangparse-r/0.4.3")
  req <- httr2::req_error(req, is_error = function(resp) FALSE)
  if (!is.null(api_key) && nzchar(api_key)) {
    req <- httr2::req_headers(req, `x-api-key` = api_key)
  }
  req
}

.perform <- function(req) {
  resp <- httr2::req_perform(req)
  status <- httr2::resp_status(resp)
  body_text <- tryCatch(
    httr2::resp_body_string(resp),
    error = function(e) ""
  )
  .stop_for_status(status, body_text)
  body_text
}

#' Unwrap a serve-API response envelope.
#'
#' On success returns the inner parsed object. On error raises an
#' \code{ailang_docparse_error}.
#'
#' @param body_text Raw JSON text returned by the API.
#' @return A parsed list (the inner result).
#' @keywords internal
.unwrap <- function(body_text) {
  if (!nzchar(body_text)) return(list())
  outer <- tryCatch(
    jsonlite::fromJSON(body_text, simplifyVector = FALSE),
    error = function(e) {
      stop(.docparse_error(sprintf("Invalid JSON response: %s", conditionMessage(e))))
    }
  )
  if (!is.null(outer$error) && length(outer$error) > 0L) {
    err <- outer$error
    if (is.character(err)) stop(.docparse_error(err))
    # Dict errors (e.g. device-auth poll) — return the whole envelope so
    # the caller can inspect status fields.
    return(outer)
  }
  result_str <- outer$result
  if (is.null(result_str) || !nzchar(result_str)) return(outer)
  inner <- tryCatch(
    jsonlite::fromJSON(result_str, simplifyVector = FALSE),
    error = function(e) list(raw = result_str)
  )
  if (is.list(inner) && !is.null(inner$error) && length(inner$error) > 0L) {
    err <- inner$error
    msg <- if (is.list(err) && !is.null(err$message)) err$message else as.character(err)
    stop(.docparse_error(msg))
  }
  inner
}

#' Internal: GET or POST to a JSON API endpoint and unwrap the envelope.
#' @keywords internal
.call <- function(base_url, path, method = "GET",
                  api_key = NULL, args = NULL, timeout = 60) {
  req <- .build_request(base_url, path, api_key, timeout)
  if (identical(method, "GET")) {
    req <- httr2::req_method(req, "GET")
  } else {
    body <- if (is.null(args)) list() else list(args = args)
    req <- httr2::req_body_json(req, body, auto_unbox = FALSE)
  }
  .unwrap(.perform(req))
}
