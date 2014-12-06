Conditions effectively work like basic IF statements, where Flags refer to the various conditions required to suceed, and Results define the outcome. The syntax is:
    "Condition"
    	{
    	"flag"	"val"
    	"type" "AND/OR"
    	"Result"
    		{
    			"resultValue" "prop"
    		}
    	}
Type defines the mode used to decide whether it suceeds. AND means all flags must evaluate to true before the condition itself suceeds, whereas OR only needs one flag before it succeeds. Every instance in the map has each condition evaluated on it. Some results will be removed if they can only be executed once (mainly AddGlobal). If no results are left, the condition itself is deleted. If no flags exist, the condition always executes.
##Flags:
- IfMode = COOP/SP
  True if the map is the specified mode.
- IfPreview = 1/0
  If the map is in preview mode (not publishing) this evaluates to true.
- HasInst = "instances/p2editor/file.vmf"
  True if the map has at least one instance with the specified name (not necersarily the current instance).
- Instance = "instances/p2editor/file.vmf"
  True if the current instance exactly matches the given filename.
- InstFlag = "door_entry_coop_"
  True if the current instance contains the given name ("elevator_" matches "elevator_entrance", "files/elevator_/elevator_exit", etc)
- ifStyleTrue = varName
  True if the style variable is also true
- ifStyleFalse = varName
  False if the style variable is also false
- Has = "goo"
  True if an item has the matching voice attribute 
- NotHas = "blueGel"
  True if no item has the matching voice attribute
  
## Results:
- changeinstance = "instances/p2editor/file.vmf"
  Change the instance to use the given filename
- Packer = "materials/metal/bts_wall.vmt"
  Ensures the specified resource is packed into the map.
- Suffix = "suff"
  Appends the given string to the end of the instance filename, ignoring .vmf ("folder/inst.vmf" becomes "folder/inst_suff.vmf")
- InstVar = "connectionCount 0"
  Sets the specified instance $replace variable (without $) to the given value
- Variant 
  {
   Number = "3"
   Weights = "1,2,1"
  }
  Randomly chooses between several instances. Adds a suffix following the form "_var4" to the filename, from 1-number. Weights is a comma-separated list of weights to assign to the different instances. The chance to pick a particular instance is weight / total of weights. If the weight is not specifed or invalid every item is given a weight of 1. Higher numbers make that item more common.
- AddGlobal
  {
   Position = "-256 -256 0"
   File = "instances/p2editor/file.vmf"
   Name = "targetname"
  }
  Add one of the given instances to the map, at the given position and with the given targetname.
- AddOverlay
  {
	Name = "targetname"
    File = "instances/p2editor/file.vmf"
  }
  Add the specified instance on top of the current instance, with the same position and rotation. If no name is specified, it has the same name as the original instance to allow the two to communicate to each other.
- CustOutput
  {
    decConCount = "1/0"
	remIndSign = "1/0"
	AddOut = output definition
  }
  Add specialised outputs for the given item. If Decrease Connection Count is true, the $connectioncount variable will be decreased on all the targeted items so they process other output normally. If Remove Indicator Signs is true, any Check/Cross or Timer signs associated with this item's output will be deleted (leaving the bare antline). AddOut adds one output to the item per targeted item.
- CustAntline
  {
    straight = "0.25|overlays/antline_straight"
    corner = "0.25|overlays/antline_straight|static"
    instance = instances/p2editor_clean/hmw/sendtor_antline.vmf"
	AddOut = output definition
  }
  Allows changing the texture for the item's output antline. Straight and Corner define the used texture, broken up into 3 parts separated by "|". The first defines the sideways scale used for the texture. The second defines the material, and the last (must be "static") removes the targetname of the overlay (so no info_overlay_acessor entities are created, if the texture does not toggle). Only the first two are required. If instance is present, it provides a path for a replacement version of indicator_toggle to use with the given antlines. Any AddOut command targets this toggle entity.



StyleVar
  {
    setTrue = "variable"
	setFalse = "variable"
  }
  Sets the value of a style variable. Any number of variables may be listed per StyleVar command.
  
Has
  {
    attrName = 1/0
  } 
  Indicates that this attribute is present (1) or nor present (0) in the map. AttrName is the attribute itself.

StyleOpt
  {
    option = value
  }
  Sets the value of the specifed property in the option (For example, this could modify the glass_scale property to change the scaling depending on whether a certain instance is present or not).

#AddOut:
  {
	"output" "OnTrigger"
	"targ_out"	"out_relay"
	"input"		"Trigger"
	"targ_in"	"special_in_relay"
  }
  This is avalible on both CustOutput and CustAntline, and specifies additional outputs that should be appended to the target item. Output defines the output on the item that will be used, whereas Input defines the input that is used on the target. targ_out is the targetname of the internal instance entity that generates the output. targ_in is the targetname of the internal instance entity the output ultimately is aimed at. If targ_out or targ_in do not exist, it will be treated as a regular in/output