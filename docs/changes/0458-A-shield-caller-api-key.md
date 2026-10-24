# Shield caller authentication modes

`agents.examples.shield_caller.screen_message` can call either the unkeyed Shield core endpoint or the keyed Shield product API. When `api_key` is omitted, the caller sends no authentication header; this supports the unkeyed core service. The product `/v1` API requires `X-API-Key` or `Authorization: Bearer`, so a caller targeting that service must pass its key explicitly and the caller sends it as `X-API-Key`.

The helper does not read environment variables or discover credentials. A provided key must be a nonempty string of printable ASCII without spaces or control characters; invalid values fail closed before an opener is built. The key is not included in the response or logs. Redirects remain disabled, and transport or response failures still return the fixed sanitized block.
