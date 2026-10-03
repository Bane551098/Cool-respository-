-- SutherlandAnimator (ModuleScript)
--
-- Plays the Sutherland model's animations (the 8 that ship with its rig)
-- and draws the slash harken cables. Put this ModuleScript in
-- ReplicatedStorage and call it from the script that controls the mech:
--
--   local SutherlandAnimator = require(ReplicatedStorage.SutherlandAnimator)
--   local anim = SutherlandAnimator.new(workspace.Sutherland)
--   anim:setMovement(speed, useLandspinners)  -- every frame / on input
--   anim:fire()
--   anim:harken()
--   anim:tonfa("L")
--   anim:scan()
--
-- Fill ANIMATION_IDS with the asset ids you get when you publish each
-- Sutherland_<Name>.fbx from the Animation Editor (see sutherland/README.md).

local RunService = game:GetService("RunService")

local ANIMATION_IDS = {
	Idle = "rbxassetid://0",
	Walk = "rbxassetid://0",
	LandspinnerDash = "rbxassetid://0",
	RifleFire = "rbxassetid://0",
	SlashHarken = "rbxassetid://0",
	TonfaStrikeL = "rbxassetid://0",
	TonfaStrikeR = "rbxassetid://0",
	FactsphereScan = "rbxassetid://0",
}

local MOVEMENT = { "Idle", "Walk", "LandspinnerDash" }
local CHEST_BONE = "Chest"
local HARKEN_BONES = { "Harken.L", "Harken.R" }

local WALK_SPEED_AT_1X = 8 -- studs/s the Walk cycle looks right at
local SPIN_SPEED_AT_1X = 40 -- studs/s the LandspinnerDash loop looks right at
local MOVE_THRESHOLD = 0.5

type Cable = { beam: Beam, mount: Attachment, offset: CFrame }

local SutherlandAnimator = {}
SutherlandAnimator.__index = SutherlandAnimator

local function findAnimator(model: Model): Animator
	local animator = model:FindFirstChildWhichIsA("Animator", true)
	if animator then
		return animator
	end
	local controller = model:FindFirstChildWhichIsA("AnimationController", true)
	if not controller then
		controller = Instance.new("AnimationController")
		controller.Parent = model
	end
	animator = Instance.new("Animator")
	animator.Parent = controller
	return animator
end

local function findBone(model: Model, name: string): Bone?
	for _, d in model:GetDescendants() do
		if d:IsA("Bone") and d.Name == name then
			return d
		end
	end
	return nil
end

function SutherlandAnimator.new(model: Model)
	local self = setmetatable({
		model = model,
		animator = findAnimator(model),
		tracks = {} :: { [string]: AnimationTrack },
		cables = {} :: { Cable },
		chest = nil :: Bone?,
		moveState = "",
		connection = nil :: RBXScriptConnection?,
	}, SutherlandAnimator)

	for name, id in ANIMATION_IDS do
		local animation = Instance.new("Animation")
		animation.Name = name
		animation.AnimationId = id
		local track = self.animator:LoadAnimation(animation)
		if table.find(MOVEMENT, name) then
			track.Priority = Enum.AnimationPriority.Movement
			track.Looped = true
		elseif name == "FactsphereScan" then
			track.Priority = Enum.AnimationPriority.Idle
		else
			track.Priority = Enum.AnimationPriority.Action
			track.Looped = false
		end
		self.tracks[name] = track
	end

	self:_setupCables()
	self:setMovement(0, false)
	return self
end

-- Movement layer: Idle / Walk / LandspinnerDash, speed-matched.
function SutherlandAnimator:setMovement(speed: number, useLandspinners: boolean)
	local state = "Idle"
	if speed > MOVE_THRESHOLD then
		state = if useLandspinners then "LandspinnerDash" else "Walk"
	end
	if state ~= self.moveState then
		for _, name in MOVEMENT do
			local track = self.tracks[name]
			if name == state then
				track:Play(0.3)
			elseif track.IsPlaying then
				track:Stop(0.3)
			end
		end
		self.moveState = state
	end
	if state == "Walk" then
		self.tracks.Walk:AdjustSpeed(speed / WALK_SPEED_AT_1X)
	elseif state == "LandspinnerDash" then
		self.tracks.LandspinnerDash:AdjustSpeed(math.clamp(speed / SPIN_SPEED_AT_1X, 0.5, 3))
	end
end

function SutherlandAnimator:fire()
	self.tracks.RifleFire:Play(0.1)
end

function SutherlandAnimator:tonfa(side: "L" | "R")
	self.tracks["TonfaStrike" .. side]:Play(0.1)
end

function SutherlandAnimator:scan()
	self.tracks.FactsphereScan:Play(0.2)
end

-- Slash harkens: plays the launch animation; the cables follow the harken bones.
function SutherlandAnimator:harken()
	for _, cable in self.cables do
		cable.beam.Enabled = true
	end
	local track = self.tracks.SlashHarken
	track:Play(0.05)
	track.Stopped:Once(function()
		for _, cable in self.cables do
			cable.beam.Enabled = false
		end
	end)
end

-- One Beam per harken, from a mount point that rides on the Chest bone to
-- the harken bone (Bones are Attachments, so a Beam can end on one).
function SutherlandAnimator:_setupCables()
	local chest = findBone(self.model, CHEST_BONE)
	if not chest then
		warn("SutherlandAnimator: no " .. CHEST_BONE .. " bone found; harken cables disabled")
		return
	end
	self.chest = chest
	for _, boneName in HARKEN_BONES do
		local bone = findBone(self.model, boneName)
		local holder = bone and bone:FindFirstAncestorWhichIsA("BasePart")
		if bone and holder then
			local mount = Instance.new("Attachment")
			mount.Name = boneName .. "_Mount"
			mount.Parent = holder
			mount.WorldCFrame = bone.TransformedWorldCFrame

			local beam = Instance.new("Beam")
			beam.Name = boneName .. "_Cable"
			beam.Attachment0 = mount
			beam.Attachment1 = bone
			beam.Width0 = 0.15
			beam.Width1 = 0.15
			beam.Color = ColorSequence.new(Color3.fromRGB(60, 60, 66))
			beam.LightInfluence = 1
			beam.FaceCamera = true
			beam.Segments = 1
			beam.Enabled = false
			beam.Parent = holder

			table.insert(self.cables, {
				beam = beam,
				mount = mount,
				offset = chest.TransformedWorldCFrame:ToObjectSpace(bone.TransformedWorldCFrame),
			})
		end
	end

	-- Keep each cable's start point on the chest as the body animates.
	self.connection = RunService.Heartbeat:Connect(function()
		for _, cable in self.cables do
			if cable.beam.Enabled then
				cable.mount.WorldCFrame = chest.TransformedWorldCFrame * cable.offset
			end
		end
	end)
end

function SutherlandAnimator:destroy()
	if self.connection then
		self.connection:Disconnect()
	end
	for _, track in self.tracks do
		track:Stop(0)
		track:Destroy()
	end
	for _, cable in self.cables do
		cable.beam:Destroy()
		cable.mount:Destroy()
	end
end

return SutherlandAnimator
