-- Cipher.lua
-- Exports character state and AH prices to SavedVariables for AI analysis.
-- Account-wide data (prices) → CipherDB
-- Per-character data (gear, bags, bank, talents, professions) → CipherCharDB

local ADDON_NAME = "Cipher"
local VERSION = 1

-- Compatibility: these APIs moved to C_Container namespace in retail but
-- remain as globals in TBC Anniversary (Interface 20505). Wrap anyway for safety.
local ContainerNumSlots = (C_Container and C_Container.GetContainerNumSlots) or GetContainerNumSlots
local ContainerItemLink  = (C_Container and C_Container.GetContainerItemLink)  or GetContainerItemLink
local ContainerItemInfo  = (C_Container and C_Container.GetContainerItemInfo)  or GetContainerItemInfo

local frame = CreateFrame("Frame", "CipherFrame")
frame:RegisterEvent("ADDON_LOADED")
frame:RegisterEvent("PLAYER_LOGIN")
frame:RegisterEvent("PLAYER_ENTERING_WORLD")
frame:RegisterEvent("TRADE_SKILL_SHOW")
frame:RegisterEvent("TRADE_SKILL_CLOSE")
frame:RegisterEvent("CRAFT_SHOW")
frame:RegisterEvent("CRAFT_CLOSE")
frame:RegisterEvent("BANKFRAME_OPENED")

local pricesCollected      = false
local professionsCollected = false
local tsmPricesCollected   = false

-- ============================================================
-- Helpers
-- ============================================================

local function cprint(msg)
    print("|cff88ccffCipher:|r " .. msg)
end

-- GetItemStats returns bonus stats for an item link (TBC Anniversary has this API).
-- Fills a provided table with ITEM_MOD_* keys. Safe to call when API absent.
local function CollectItemStats(link)
    if not link or not GetItemStats then return nil end
    local t = {}
    GetItemStats(link, t)
    -- Remove zero/empty entries and non-stat metadata keys
    local out = {}
    for k, v in pairs(t) do
        if type(v) == "number" and v ~= 0 then
            out[k] = v
        end
    end
    return next(out) and out or nil
end

-- GetContainerItemInfo returns a table in retail but multiple values in classic.
-- Returns: link (string), count (number)
local function GetBagSlot(bagID, slot)
    local link = ContainerItemLink(bagID, slot)
    if not link then return nil, nil end

    local info = { ContainerItemInfo(bagID, slot) }
    local count
    if type(info[1]) == "table" then
        -- Retail table form: info[1].stackCount
        count = info[1].stackCount or 1
    else
        -- Classic multi-value form: icon, count, locked, quality, ...
        count = info[2] or 1
    end
    return link, count
end

-- ============================================================
-- Collection functions
-- ============================================================

local function CollectCharacter()
    local _, classFile, classId   = UnitClass("player")
    local _, raceFile,  raceId    = UnitRace("player")
    return {
        exportedAt = time(),
        name       = UnitName("player"),
        realm      = GetRealmName(),
        level      = UnitLevel("player"),
        faction    = UnitFactionGroup("player"),
        class      = classFile,
        classId    = classId,
        race       = raceFile,
        raceId     = raceId,
    }
end

local function CollectGear()
    local gear = {}
    -- INVSLOT_FIRST_EQUIPPED = 1, INVSLOT_LAST_EQUIPPED = 19 (FrameXML globals)
    for slot = INVSLOT_FIRST_EQUIPPED, INVSLOT_LAST_EQUIPPED do
        local link = GetInventoryItemLink("player", slot)
        if link then
            gear[slot] = { link = link, stats = CollectItemStats(link) }
        end
    end
    return gear
end

local function CollectBags()
    local bags = {}
    for bagID = 0, 4 do
        local numSlots = ContainerNumSlots(bagID)
        if numSlots and numSlots > 0 then
            bags[bagID] = {}
            for slot = 1, numSlots do
                local link, count = GetBagSlot(bagID, slot)
                if link then
                    bags[bagID][slot] = { link = link, count = count, stats = CollectItemStats(link) }
                end
            end
        end
    end
    return bags
end

local function CollectBank()
    local bank = {}

    -- Main bank container: BANK_CONTAINER = -1, always 28 slots
    local mainSlots = ContainerNumSlots(-1)
    if mainSlots and mainSlots > 0 then
        bank[-1] = {}
        for slot = 1, mainSlots do
            local link, count = GetBagSlot(-1, slot)
            if link then
                bank[-1][slot] = { link = link, count = count, stats = CollectItemStats(link) }
            end
        end
    end

    -- Purchased bank bag slots: BankBag_1=5 through BankBag_7=11
    local numPurchased = GetNumBankSlots()
    for i = 1, numPurchased do
        local bagID    = 4 + i
        local numSlots = ContainerNumSlots(bagID)
        if numSlots and numSlots > 0 then
            bank[bagID] = {}
            for slot = 1, numSlots do
                local link, count = GetBagSlot(bagID, slot)
                if link then
                    bank[bagID][slot] = { link = link, count = count, stats = CollectItemStats(link) }
                end
            end
        end
    end

    return bank
end

local function CollectTalents()
    local allSpecs = {}
    if not (GetNumTalentTabs and GetNumTalents and GetTalentInfo and GetTalentTabInfo) then
        return allSpecs
    end

    local numGroups  = GetNumTalentGroups and GetNumTalentGroups() or 1
    local activeGroup = GetActiveTalentGroup and GetActiveTalentGroup() or 1

    for group = 1, numGroups do
        local spec = { active = (group == activeGroup), trees = {} }
        local numTabs = GetNumTalentTabs()
        for tabIndex = 1, numTabs do
            local _, tabName, _, _, pointsSpent = GetTalentTabInfo(tabIndex, false, false, group)
            local tree = { name = tabName, pointsSpent = pointsSpent or 0, talents = {} }

            local numTalents = GetNumTalents(tabIndex)
            for talentIndex = 1, numTalents do
                local tName, _, tier, column, rank, maxRank = GetTalentInfo(tabIndex, talentIndex, false, false, group)
                if rank and rank > 0 then
                    table.insert(tree.talents, {
                        name    = tName,
                        tier    = tier,
                        column  = column,
                        rank    = rank,
                        maxRank = maxRank,
                    })
                end
            end

            table.insert(spec.trees, tree)
        end
        table.insert(allSpecs, spec)
    end
    return allSpecs
end

-- GetProfessions() returns nil in TBC Anniversary. Use GetSkillLineInfo instead.
-- ExpandSkillHeader(0) fires SKILL_LINES_CHANGED, so guard against re-entry.
local SECONDARY_PROFESSIONS = { ["Cooking"] = true, ["First Aid"] = true, ["Fishing"] = true }
local collectingProfessions = false

local function CollectProfessions()
    local professions = {}
    if not (GetNumSkillLines and GetSkillLineInfo) then return professions end
    if collectingProfessions then return professions end

    collectingProfessions = true
    ExpandSkillHeader(0)  -- expand all collapsed headers; triggers SKILL_LINES_CHANGED (guarded above)

    for i = 1, GetNumSkillLines() do
        local name, isHeader, _, rank, _, _, maxRank, isAbandonable = GetSkillLineInfo(i)
        if not name then break end
        if not isHeader and (isAbandonable or SECONDARY_PROFESSIONS[name]) then
            table.insert(professions, { name = name, level = rank, maxLevel = maxRank })
        end
    end
    collectingProfessions = false
    return professions
end

local function ExtractItemID(link)
    if not link then return nil end
    return tonumber(link:match("|Hitem:(%d+):"))
end

local function CollectTSMPrices()
    if not (TSM_API and TSM_API.GetCustomPriceValue) then
        return nil, "TSM not present"
    end

    -- Build item ID universe from Auctionator scan + gear/bags/bank
    local seen = {}

    local realm   = GetRealmName() .. " " .. UnitFactionGroup("player")
    local realmDB = AUCTIONATOR_PRICE_DATABASE and AUCTIONATOR_PRICE_DATABASE[realm]
    if type(realmDB) == "table" then
        for key in pairs(realmDB) do
            local id = tonumber(key)
            if id and id > 0 then seen[id] = true end
        end
    end

    -- Also include any items in gear/bags/bank not covered by Auctionator
    local function addLink(link)
        local id = ExtractItemID(link)
        if id and id > 0 then seen[id] = true end
    end
    for _, slot in pairs(CipherCharDB.gear or {}) do
        addLink(type(slot) == "table" and slot.link or slot)
    end
    for _, bag in pairs(CipherCharDB.bags or {}) do
        if type(bag) == "table" then
            for _, entry in pairs(bag) do
                if type(entry) == "table" then addLink(entry.link) end
            end
        end
    end
    for _, bag in pairs(CipherCharDB.bank or {}) do
        if type(bag) == "table" then
            for _, entry in pairs(bag) do
                if type(entry) == "table" then addLink(entry.link) end
            end
        end
    end

    local itemCount = 0
    for _ in pairs(seen) do itemCount = itemCount + 1 end
    if itemCount == 0 then
        return nil, "no items found"
    end

    local prices = {}
    local count  = 0
    for itemID in pairs(seen) do
        local itemString = "i:" .. itemID
        local market     = TSM_API.GetCustomPriceValue("dbmarket",    itemString)
        local minbuyout  = TSM_API.GetCustomPriceValue("dbminbuyout", itemString)
        if market or minbuyout then
            prices[tostring(itemID)] = { dbmarket = market, dbminbuyout = minbuyout }
            count = count + 1
        end
    end
    return prices, count
end

local function CollectAuctionatorPrices()
    if not (Auctionator and Auctionator.API and Auctionator.API.v1) then
        return nil, "Auctionator not present"
    end
    if not (Auctionator.State and Auctionator.State.Loaded) then
        return nil, "Auctionator not yet initialized"
    end

    local realm   = GetRealmName() .. " " .. UnitFactionGroup("player")
    local realmDB = AUCTIONATOR_PRICE_DATABASE and AUCTIONATOR_PRICE_DATABASE[realm]

    if type(realmDB) ~= "table" then
        return nil, "No price table found for " .. realm
    end

    local prices = {}
    local count  = 0
    for key, itemData in pairs(realmDB) do
        -- Skip metadata keys ("version" etc.); only store numeric item ID keys with a price
        if key ~= "version" and type(itemData) == "table" and itemData.m then
            prices[key] = itemData.m
            count = count + 1
        end
    end

    return prices, realm, count
end

-- ============================================================
-- Export
-- ============================================================

local function CollectAndReportPrices()
    local prices, realm, count = CollectAuctionatorPrices()
    if prices then
        CipherDB.prices         = prices
        CipherDB.priceRealm     = realm
        CipherDB.priceCount     = count
        CipherDB.priceUpdatedAt = time()
        cprint(count .. " AH prices captured.")
    else
        -- when prices is nil, realm holds the error string
        cprint("No AH prices — " .. (realm or "unknown") .. ".")
    end
    pricesCollected = true
end

local function CollectAndReportTSMPrices()
    local tsmPrices, tsmCount = CollectTSMPrices()
    if tsmPrices then
        CipherCharDB.tsmPrices = tsmPrices
        cprint(tsmCount .. " TSM prices captured.")
    else
        cprint("TSM prices — " .. (tsmCount or "unknown error") .. ".")
    end
    tsmPricesCollected = true
end

local function DoExport()
    CipherCharDB.character   = CollectCharacter()
    CipherCharDB.gear        = CollectGear()
    CipherCharDB.bags        = CollectBags()
    CipherCharDB.talents     = CollectTalents()
    CipherCharDB.professions = CollectProfessions()
    cprint(CipherCharDB.character.name .. " character data exported.")
end

-- ============================================================
-- Events
-- ============================================================

frame:SetScript("OnEvent", function(self, event, arg1)
    if event == "ADDON_LOADED" and arg1 == ADDON_NAME then
        CipherDB     = CipherDB     or { version = VERSION }
        CipherCharDB = CipherCharDB or { version = VERSION }

    elseif event == "PLAYER_LOGIN" then
        DoExport()

    elseif event == "PLAYER_ENTERING_WORLD" then
        if not pricesCollected then
            CollectAndReportPrices()
        end
        if not tsmPricesCollected then
            CollectAndReportTSMPrices()
        end

    elseif event == "TRADE_SKILL_SHOW" or event == "CRAFT_SHOW" then
        if not professionsCollected then
            CipherCharDB.professions = CollectProfessions()
            if #CipherCharDB.professions > 0 then
                local names = {}
                for _, p in ipairs(CipherCharDB.professions) do
                    table.insert(names, p.name .. " " .. p.level)
                end
                cprint("Professions: " .. table.concat(names, ", "))
            end
            professionsCollected = true
        end

    elseif event == "TRADE_SKILL_CLOSE" or event == "CRAFT_CLOSE" then
        professionsCollected = false

    elseif event == "BANKFRAME_OPENED" then
        CipherCharDB.bank            = CollectBank()
        CipherCharDB.bankUpdatedAt   = time()
        cprint("Bank snapshot updated.")
    end
end)

-- ============================================================
-- Slash command: /cipher
-- ============================================================

SLASH_CIPHER1 = "/cipher"
SlashCmdList["CIPHER"] = function()
    DoExport()
    pricesCollected    = false
    tsmPricesCollected = false
    professionsCollected = false
    CollectAndReportPrices()
    CollectAndReportTSMPrices()
end
