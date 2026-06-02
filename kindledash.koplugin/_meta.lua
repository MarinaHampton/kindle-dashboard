local _ = require("gettext")
return {
    name = "kindledash",
    fullname = _("Homelab dashboard"),
    description = _("Fetches the homelab e-ink dashboard pages, shows them full-screen, "
        .. "pages through them with the page-turn buttons, and auto-refreshes."),
}
