-- SutherlandAnimator (ModuleScript)
--
-- Drives the Sutherland's imported animations and draws the slash harken
-- cables. Put this ModuleScript in ReplicatedStorage and call it from the
-- script that controls the mech:
--
--   local SutherlandAnimator = require(ReplicatedStorage.SutherlandAnimator)
--   local anim = SutherlandAnimator.new(workspace.Sutherland)
--   anim:setMovement(speed, useLandspinners)  -- every frame / on input
--   anim:setAiming(true)
--   anim:fire()
--   anim:harken("L")
--
-- Fill ANIMATION_IDS with the asset ids you get when you publish each
-- animation from the Animation Editor (see sutherland/README.md).

local RunService = game:GetService("RunService")

local ANIMATION_IDS = {
	Idle = "rbxassetid://0",
	Walk = "rbxassetid://0",
	Landspinner = "rbxassetid://0",
	Aim = "rbxassetid://0",
	Fire = "rbxassetid://0",
	Harken_L = "rbxassetid://0",
	Harken_R = "rbxassetid://0",
}

local WALK_SPEED_AT_1X = 8 -- studs/s the Walk cycle was authored for
local SPIN_SPEED_AT_1X = 40 -- studs/s the Landspinner loop looks right at
local MOVE_THRESHOLD = 0.5

local SutherlandAnimator = {}
SutherlandAnimator.__index = SutherlandAnimator

export type SutherlandAnimator = typeof(setmetatable({} :: {
	model: Model,
	animator: Animator,
	tracks: { [string]: AnimationTrack },
	cables: { [string]: { beam: Beam, mount: Attachment, bone: Bone, torso: Bone, offset: CFrame } },
	aiming: boolean,
	moveState: string,
	connection: RBXScriptConnection?,
}, SutherlandAnimator))

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

function SutherlandAnimator.new(model: Model): SutherlandAnimator
	local self = setmetatable({
		model = model,
		animator = findAnimator(model),
		tracks = {},
		cables = {},
		aiming = false,
		moveState = "",
		connection = nil,
	}, SutherlandAnimator)

	for name, id in ANIMATION_IDS do
		local animation = Instance.new("Animation")
		animation.Name = name
		animation.AnimationId = id
		local track = self.animator:LoadAnimation(animation)
		if name == "Idle" or name == "Walk" or name == "Landspinner" then
			track.Priority = Enum.AnimationPriority.Movement
			track.Looped = true
		elseif name == "Aim" then
			track.Priority = Enum.AnimationPriority.Action
		else
			track.Priority = Enum.AnimationPriority.Action2
		end
		self.tracks[name] = track
	end

	self:_setupCables()
	self:setMovement(0, false)
	return self
end

-- Movement layer: Idle / Walk / Landspinner, speed-matched.
function SutherlandAnimator.setMovement(self: SutherlandAnimator, speed: number, useLandspinners: boolean)
	local state = "Idle"
	if speed > MOVE_THRESHOLD then
		state = if useLandspinners then "Landspinner" else "Walk"
	end
	if state ~= self.moveState then
		for _, name in { "Idle", "Walk", "Landspinner" } do
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
	elseif state == "Landspinner" then
		self.tracks.Landspinner:AdjustSpeed(math.clamp(speed / SPIN_SPEED_AT_1X, 0.5, 3))
	end
end

-- Aim: raises the rifle and freezes on the last frame until released.
function SutherlandAnimator.setAiming(self: SutherlandAnimator, aiming: boolean)
	if aiming == self.aiming then
		return
	end
	self.aiming = aiming
	local track = self.tracks.Aim
	if aiming then
		track:Play(0.15)
		task.delay(track.Length > 0 and track.Length * 0.95 or 0.6, function()
			if self.aiming and track.IsPlaying then
				track:AdjustSpeed(0) -- hold the aim pose
			end
		end)
	else
		track:AdjustSpeed(1)
		track:Stop(0.25)
	end
end

-- Fire: one recoil cycle. Call repeatedly for bursts; aims first if needed.
function SutherlandAnimator.fire(self: SutherlandAnimator)
	if not self.aiming then
		self:setAiming(true)
	end
	local track = self.tracks.Fire
	track.Looped = false
	track:Play(0.02)
end

-- Slash harken: plays the launch animation; the cable follows the harken bone.
function SutherlandAnimator.harken(self: SutherlandAnimator, side: "L" | "R")
	local track = self.tracks["Harken_" .. side]
	local cable = self.cables[side]
	if cable then
		cable.beam.Enabled = true
	end
	track:Play(0.05)
	track.Stopped:Once(function()
		if cable then
			cable.beam.Enabled = false
		end
	end)
end

-- One Beam per harken, from a mount point that rides on the Torso bone to
-- the Harken bone (Bones are Attachments, so a Beam can end on one).
function SutherlandAnimator._setupCables(self: SutherlandAnimator)
	local torso = findBone(self.model, "Torso")
	if not torso then
		warn("SutherlandAnimator: no Torso bone found; harken cables disabled")
		return
	end
	for _, side in { "L", "R" } do
		local bone = findBone(self.model, "Harken_" .. side)
		local holder = bone and bone:FindFirstAncestorWhichIsA("BasePart")
		if bone and holder then
			local mount = Instance.new("Attachment")
			mount.Name = "HarkenMount_" .. side
			mount.Parent = holder
			mount.WorldCFrame = bone.TransformedWorldCFrame

			local beam = Instance.new("Beam")
			beam.Name = "HarkenCable_" .. side
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

			self.cables[side] = {
				beam = beam,
				mount = mount,
				bone = bone,
				torso = torso,
				offset = torso.TransformedWorldCFrame:ToObjectSpace(bone.TransformedWorldCFrame),
			}
		end
	end

	-- Keep each cable's start point on the chest as the torso animates.
	self.connection = RunService.Heartbeat:Connect(function()
		for _, cable in self.cables do
			if cable.beam.Enabled then
				cable.mount.WorldCFrame = cable.torso.TransformedWorldCFrame * cable.offset
			end
		end
	end)
end

function SutherlandAnimator.destroy(self: SutherlandAnimator)
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
