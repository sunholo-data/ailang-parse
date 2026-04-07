#' AILANG Parse key management
#'
#' R6 class for listing, revoking, rotating and inspecting API keys.
#' Access via the \code{$keys} field of a \code{\link{DocParse}} client; you
#' do not normally instantiate this class directly. To create a new key,
#' use \code{client$device_auth("my-label")}.
#'
#' @examples
#' \dontrun{
#' client <- DocParse$new()
#' client$keys$list()
#' client$keys$usage("key-id")
#' }
#' @export
KeyManager <- R6::R6Class(
  "KeyManager",
  public = list(
    #' @description Construct a key manager bound to a client.
    #' @param client A \code{DocParse} instance.
    initialize = function(client) {
      private$client <- client
      invisible(self)
    },

    #' @description List API keys for a user.
    #' @param user_id Opaque user identifier (default: empty).
    list = function(user_id = "") {
      .call(private$client$base_url, "/api/v1/keys/list", "POST",
            private$client$api_key, args = list(user_id),
            timeout = private$client$timeout)
    },

    #' @description Revoke an API key.
    #' @param key_id Key identifier to revoke.
    #' @param user_id Opaque user identifier (default: empty).
    revoke = function(key_id, user_id = "") {
      .call(private$client$base_url, "/api/v1/keys/revoke", "POST",
            private$client$api_key, args = list(key_id, user_id),
            timeout = private$client$timeout)
    },

    #' @description Rotate a key — generates a new key, revokes the old
    #'   one and preserves the tier.
    #' @param key_id Key identifier to rotate.
    #' @param user_id Opaque user identifier (default: empty).
    rotate = function(key_id, user_id = "") {
      .key_info_from_list(
        .call(private$client$base_url, "/api/v1/keys/rotate", "POST",
              private$client$api_key, args = list(key_id, user_id),
              timeout = private$client$timeout)
      )
    },

    #' @description Get usage statistics for a key.
    #' @param key_id Key identifier.
    #' @param user_id Opaque user identifier (default: empty).
    usage = function(key_id, user_id = "") {
      .usage_info_from_list(
        .call(private$client$base_url, "/api/v1/keys/usage", "POST",
              private$client$api_key, args = list(key_id, user_id),
              timeout = private$client$timeout)
      )
    }
  ),
  private = list(
    client = NULL
  )
)
