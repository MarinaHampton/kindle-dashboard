--[[
Homelab dashboard plugin for KOReader (Kindle 4).

Pulls page0..pageN.png from the homelab endpoint, shows the current page
full-screen, cycles pages with the physical page-turn buttons, and
auto-refreshes on a timer. Back/Home closes it; Menu forces a refresh.
]]--

local Device = require("device")
local UIManager = require("ui/uimanager")
local WidgetContainer = require("ui/widget/container/widgetcontainer")
local InputContainer = require("ui/widget/container/inputcontainer")
local ImageWidget = require("ui/widget/imagewidget")
local InfoMessage = require("ui/widget/infomessage")
local DataStorage = require("datastorage")
local lfs = require("libs/libkoreader-lfs")
local logger = require("logger")
local _ = require("gettext")
local Screen = Device.screen

local BASE = "http://192.168.1.20:8137"
local CACHE = DataStorage:getDataDir() .. "/cache/kindledash"
local REFRESH_SEC = 30

-- HTTP GET. With `path`, streams to that file and returns the status code.
-- Without `path`, returns (code, body_string).
local function http_get(url, path)
    local http = require("socket.http")
    local ltn12 = require("ltn12")
    local socketutil = require("socketutil")
    socketutil:set_timeout(10, 30)
    local code
    if path then
        local tmp = path .. ".tmp"
        local fh = io.open(tmp, "wb")
        if not fh then socketutil:reset_timeout(); return nil end
        local ok, c = http.request{ url = url, sink = ltn12.sink.file(fh) }
        socketutil:reset_timeout()
        if ok and (c == 200 or c == nil) then
            os.rename(tmp, path)
            return 200
        end
        os.remove(tmp)
        return type(c) == "number" and c or nil
    else
        local body = {}
        local ok, c = http.request{ url = url, sink = ltn12.sink.table(body) }
        socketutil:reset_timeout()
        if ok then return (type(c) == "number" and c or 200), table.concat(body) end
        return nil
    end
end

-- ============================ the display widget ============================
local Dashboard = InputContainer:extend{
    pages = nil,   -- list of local PNG paths
    idx = 1,
}

function Dashboard:init()
    self.dimen = Screen:getSize()
    self.covers_fullscreen = true
    -- Key bindings mirror ReaderPaging's exact format on this build:
    -- triple-nested keydef + explicit event=. (Earlier version was one level
    -- short and omitted event=, so NOTHING bound — not even exit.)
    self.key_events = {
        DashNext    = { { { "RPgFwd", "LPgFwd", "Right" } }, event = "DashNext" },
        DashNextAlt = { { { "Down" } },                     event = "DashNext" },
        DashPrev    = { { { "RPgBack", "LPgBack", "Left" } }, event = "DashPrev" },
        DashPrevAlt = { { { "Up" } },                       event = "DashPrev" },
        DashClose   = { { { "Back", "Home" } },             event = "DashClose" },
        DashRefresh = { { { "Menu" } },                     event = "DashRefresh" },
    }
    self:loadPages()
    self:render()
    self.refresh_task = function() self:autoRefresh() end
    UIManager:scheduleIn(REFRESH_SEC, self.refresh_task)
    -- Keep the device awake while the dashboard is on screen (it's a
    -- wall-powered always-on panel); released again in onDashClose.
    UIManager:preventStandby()
    self.standby_prevented = true
end

-- Refresh immediately when the device wakes, so a glance always shows "now".
function Dashboard:onResume()
    self:loadPages()
    self:render()
    return false  -- don't swallow; let others handle Resume too
end

function Dashboard:loadPages()
    lfs.mkdir(CACHE)
    local count = 5
    local code, body = http_get(BASE .. "/index.json")
    if body then
        local c = body:match('"count"%s*:%s*(%d+)')
        if c then count = tonumber(c) end
    end
    local pages = {}
    for i = 0, count - 1 do
        local p = CACHE .. "/page" .. i .. ".png"
        local rc = http_get(BASE .. "/page" .. i .. ".png", p)
        if rc == 200 and lfs.attributes(p, "mode") == "file" then
            table.insert(pages, p)
        end
    end
    if #pages > 0 then
        self.pages = pages
        if self.idx > #pages then self.idx = 1 end
    end
end

function Dashboard:render()
    if self[1] and self[1].free then self[1]:free() end
    if not self.pages or #self.pages == 0 then
        self[1] = InfoMessage:new{
            text = _("Homelab dashboard: server unreachable.\nCheck wifi, then press Menu to retry."),
        }
    else
        -- file_do_cache=false is essential: ImageWidget's cache is keyed on
        -- filename only (no mtime), so without this a re-downloaded page0.png
        -- with the same name returns the STALE cached bitmap → frozen clock.
        self[1] = ImageWidget:new{ file = self.pages[self.idx], file_do_cache = false }
    end
    UIManager:setDirty(self, function() return "full", self.dimen end)
end

function Dashboard:onDashNext()
    if self.pages and self.idx < #self.pages then
        self.idx = self.idx + 1
        self:render()
    end
    return true
end

function Dashboard:onDashPrev()
    if self.pages and self.idx > 1 then
        self.idx = self.idx - 1
        self:render()
    end
    return true
end

function Dashboard:onDashRefresh()
    self:loadPages()
    self:render()
    return true
end

function Dashboard:autoRefresh()
    -- Minute timer: only re-fetch the page currently on screen (page 0 is the
    -- clock; agenda pages don't change minute-to-minute), so the slow K4 wifi
    -- isn't pulling all pages every minute. Never let a transient network
    -- error break the loop: always reschedule, even if fetch/render throws.
    pcall(function()
        local p = CACHE .. "/page" .. (self.idx - 1) .. ".png"
        if http_get(BASE .. "/page" .. (self.idx - 1) .. ".png", p) == 200 then
            self:render()
        end
    end)
    UIManager:scheduleIn(REFRESH_SEC, self.refresh_task)
end

function Dashboard:onDashClose()
    if self.refresh_task then UIManager:unschedule(self.refresh_task) end
    if self.standby_prevented then
        UIManager:allowStandby()
        self.standby_prevented = false
    end
    UIManager:close(self)
    return true
end

-- ============================== plugin module ==============================
local KindleDash = WidgetContainer:extend{
    name = "kindledash",
}

function KindleDash:init()
    self.ui.menu:registerToMainMenu(self)
end

function KindleDash:addToMainMenu(menu_items)
    menu_items.kindledash = {
        text = _("Homelab dashboard"),
        sorting_hint = "tools",
        callback = function()
            UIManager:show(Dashboard:new{})
        end,
    }
end

return KindleDash
