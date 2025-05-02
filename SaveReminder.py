bl_info = {
    "name": "Save Reminder",
    "author": "TohruTheDragon",
    "version": (1, 2),
    "blender": (2, 80, 0),
    "location": "View3D > UI > Save Reminder",
    "description": "Displays a reminder when the user hasn't saved for a while",
    "warning": "",
    "doc_url": "",
    "category": "Interface",
}

import bpy
import time
import math
from bpy.app.handlers import persistent
from datetime import datetime, timedelta

# Import drawing modules
import blf
import bgl

# Global variables to track state
last_saved_time = datetime.now()
reminder_visible = False
timer = None
draw_handlers = []
flash_counter = 0  # For flashing animation

# Addon preferences class to store persistent settings
class SaveReminderPreferences(bpy.types.AddonPreferences):
    bl_idname = __name__
    
    # Time threshold settings
    days: bpy.props.IntProperty(
        name="Days",
        description="Days before reminder appears",
        default=0,
        min=0,
    )
    hours: bpy.props.IntProperty(
        name="Hours",
        description="Hours before reminder appears",
        default=0,
        min=0,
    )
    minutes: bpy.props.IntProperty(
        name="Minutes",
        description="Minutes before reminder appears",
        default=15,
        min=0,
    )
    seconds: bpy.props.IntProperty(
        name="Seconds",
        description="Seconds before reminder appears",
        default=0,
        min=0,
    )
    
    # Display settings
    color: bpy.props.FloatVectorProperty(
        name="Text Color",
        subtype='COLOR',
        default=(1.0, 0.2, 0.2, 1.0),
        size=4,
        min=0.0,
        max=1.0,
    )
    size: bpy.props.IntProperty(
        name="Text Size",
        description="Size of the reminder text",
        default=24,
        min=10,
        max=100,
    )
    enabled: bpy.props.BoolProperty(
        name="Enable Reminder",
        description="Enable or disable the save reminder",
        default=True,
    )
    flashing: bpy.props.BoolProperty(
        name="Flashing Text",
        description="Make the reminder text flash on and off",
        default=False,
    )
    flash_speed: bpy.props.FloatProperty(
        name="Flash Speed",
        description="Speed of the flashing effect (higher is faster)",
        default=1.0,
        min=0.1,
        max=5.0,
    )
    
    def draw(self, context):
        layout = self.layout
        
        # Enable/disable toggle
        layout.prop(self, "enabled")
        
        # Time settings
        box = layout.box()
        box.label(text="Time Threshold:")
        row = box.row()
        row.prop(self, "days")
        row.prop(self, "hours")
        row = box.row()
        row.prop(self, "minutes")
        row.prop(self, "seconds")
        
        # Display settings
        box = layout.box()
        box.label(text="Display Settings:")
        box.prop(self, "color")
        box.prop(self, "size")
        
        # Flashing settings
        box.prop(self, "flashing")
        if self.flashing:
            box.prop(self, "flash_speed")

# Function to get addon preferences
def get_addon_pref():
    addon_preferences = None
    try:
        addon_preferences = bpy.context.preferences.addons[__name__].preferences
    except (KeyError, AttributeError):
        pass
    return addon_preferences

# Function to convert time delta to readable string
def format_time_delta(delta):
    days = delta.days
    hours, remainder = divmod(delta.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    
    result = ""
    if days > 0:
        result += f"{days} day{'s' if days != 1 else ''} "
    if hours > 0:
        result += f"{hours} hour{'s' if hours != 1 else ''} "
    if minutes > 0:
        result += f"{minutes} minute{'s' if minutes != 1 else ''} "
    if seconds > 0 or (days == 0 and hours == 0 and minutes == 0):
        result += f"{seconds} second{'s' if seconds != 1 else ''}"
    
    return result.strip()

# Handle drawing the reminder text
def draw_reminder_callback(self, context):
    global last_saved_time, reminder_visible, flash_counter
    
    # Get addon preferences safely
    settings = get_addon_pref()
    
    if not settings or not settings.enabled or not reminder_visible:
        return
    
    # Handle flashing text
    alpha = 1.0
    if settings.flashing:
        alpha = abs(math.sin(flash_counter * settings.flash_speed))
        if alpha < 0.3:
            return
    
    # Calculate time since last save
    current_time = datetime.now()
    time_since_save = current_time - last_saved_time
    
    # Format the time for display
    time_text = format_time_delta(time_since_save)
    
    # Get dimensions for positioning
    try:
        region = context.region
        width = region.width
        height = region.height
    except:
        width = 1920
        height = 1080
    
    # Text settings
    font_id = 0
    text = f"Not saved for {time_text}"
    
    # Position (bottom left)
    x_pos = 20
    y_pos = 50
    
    # Draw text using only the most basic BLF functions
    try:
        # Basic approach with minimal parameters
        blf.position(font_id, x_pos, y_pos, 0)
        
        # Try different size methods, one should work
        try:
            # Try Blender 2.8+ method with DPI
            blf.size(font_id, settings.size, 72)
        except TypeError:
            try:
                # Try older method
                blf.size(font_id, settings.size)
            except:
                # Last resort
                pass
        
        # Set color (with different methods to handle old and new Blender)
        try:
            # Try newer method
            blf.color(font_id, 
                      settings.color[0], 
                      settings.color[1], 
                      settings.color[2], 
                      settings.color[3] * alpha)
        except TypeError:
            try:
                # Try alternate parameter order
                blf.color(settings.color[0], 
                          settings.color[1], 
                          settings.color[2], 
                          settings.color[3] * alpha)
            except:
                # Last resort
                pass
        
        # Draw the text
        blf.draw(font_id, text)
        
    except Exception as e:
        # Fallback for Blender 4.0 which may need a different approach
        # Try basic OpenGL text drawing as absolute last resort
        try:
            bgl.glColor4f(1.0, 0.0, 0.0, 1.0)
            blf.position(font_id, x_pos, y_pos, 0)
            blf.draw(font_id, "Save Reminder: " + text)
        except:
            # Silently fail if nothing works
            pass

# Update the reminder visibility status
def update_reminder_visibility():
    global last_saved_time, reminder_visible
    
    # Use a direct but very safe approach
    try:
        # Get addon preferences
        settings = get_addon_pref()
        
        if not settings:
            # No settings found, fallback to showing reminder
            reminder_visible = True
            return
        
        # Special case: if all time values are 0, show immediately if enabled
        if settings.days == 0 and settings.hours == 0 and settings.minutes == 0 and settings.seconds == 0:
            reminder_visible = settings.enabled
            return
        
        # Calculate threshold
        threshold = timedelta(
            days=settings.days,
            hours=settings.hours,
            minutes=settings.minutes,
            seconds=settings.seconds
        )
        
        # Check if enough time has passed
        current_time = datetime.now()
        time_since_save = current_time - last_saved_time
        
        # Update visibility flag
        reminder_visible = time_since_save > threshold and settings.enabled
    
    except Exception as e:
        # If anything fails, err on the safe side
        reminder_visible = True

# Handler for depsgraph updates
@persistent
def check_save_time(scene):
    update_reminder_visibility()

# Handler for file save
@persistent
def on_file_save(dummy):
    global last_saved_time, reminder_visible
    last_saved_time = datetime.now()
    reminder_visible = False  # Reset visibility when saving

# Handler for file load
@persistent
def load_handler(dummy):
    global last_saved_time
    last_saved_time = datetime.now()
    update_reminder_visibility()

# Timer function to trigger UI updates
def timer_update():
    global flash_counter
    
    # Update flash counter for animation
    flash_counter += 0.1
    
    # Redraw all 3D viewports
    try:
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == 'VIEW_3D':
                    area.tag_redraw()
    except:
        pass
    
    # Update reminder visibility
    update_reminder_visibility()
    
    # Return time until next check (0.1 second for smoother flashing)
    return 0.1

# Panel for settings
class SAVE_REMINDER_PT_settings(bpy.types.Panel):
    bl_label = "Save Reminder Settings"
    bl_idname = "SAVE_REMINDER_PT_settings"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Save Reminder'
    
    def draw(self, context):
        layout = self.layout
        
        # Get addon preferences
        addon_prefs = get_addon_pref()
        if not addon_prefs:
            layout.label(text="Error: Addon preferences not found")
            return
            
        # Display all settings from the preferences
        layout.prop(addon_prefs, "enabled")
        
        # Time settings
        box = layout.box()
        box.label(text="Time Threshold:")
        row = box.row()
        row.prop(addon_prefs, "days")
        row.prop(addon_prefs, "hours")
        row = box.row()
        row.prop(addon_prefs, "minutes")
        row.prop(addon_prefs, "seconds")
        
        # Display settings
        box = layout.box()
        box.label(text="Display Settings:")
        box.prop(addon_prefs, "color")
        box.prop(addon_prefs, "size")
        
        # Flashing settings
        box.prop(addon_prefs, "flashing")
        if addon_prefs.flashing:
            box.prop(addon_prefs, "flash_speed")
            
        # Info about preferences
        layout.operator("preferences.addon_show", text="Open Preferences").module = __name__

# Operator to open addon preferences
class SAVE_REMINDER_OT_open_prefs(bpy.types.Operator):
    bl_idname = "save_reminder.open_prefs"
    bl_label = "Open Addon Preferences"
    bl_description = "Open the addon preferences"
    
    def execute(self, context):
        bpy.ops.preferences.addon_show(module=__name__)
        return {'FINISHED'}

# Register the addon
classes = (
    SaveReminderPreferences,
    SAVE_REMINDER_PT_settings,
    SAVE_REMINDER_OT_open_prefs,
)

def register():
    print("Registering Save Reminder addon...")
    
    # Register classes
    for cls in classes:
        bpy.utils.register_class(cls)
    
    # Add handlers
    bpy.app.handlers.depsgraph_update_post.append(check_save_time)
    bpy.app.handlers.save_post.append(on_file_save)
    bpy.app.handlers.load_post.append(load_handler)
    
    # Register timer
    global timer
    if timer is None:
        timer = bpy.app.timers.register(timer_update, persistent=True)
    
    # Add drawing callbacks for all 3D views
    global draw_handlers
    draw_handlers.clear()
    
    try:
        print("Adding draw handlers...")
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == 'VIEW_3D':
                    for space in area.spaces:
                        if space.type == 'VIEW_3D':
                            handler = space.draw_handler_add(
                                draw_reminder_callback, 
                                (None, bpy.context), 
                                'WINDOW', 
                                'POST_PIXEL'
                            )
                            draw_handlers.append((space, handler))
        print(f"Added {len(draw_handlers)} draw handlers")
    except Exception as e:
        print(f"Error setting up draw handlers: {str(e)}")
    
    # Initialize
    global last_saved_time
    last_saved_time = datetime.now()
    update_reminder_visibility()
    
    print("Save Reminder addon registered successfully")

def unregister():
    print("Unregistering Save Reminder addon...")
    
    # Remove drawing callbacks
    global draw_handlers
    for space, handler in draw_handlers:
        try:
            space.draw_handler_remove(handler, 'WINDOW')
        except Exception as e:
            print(f"Error removing handler: {str(e)}")
    draw_handlers.clear()
    
    # Remove handlers
    if check_save_time in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(check_save_time)
    if on_file_save in bpy.app.handlers.save_post:
        bpy.app.handlers.save_post.remove(on_file_save)
    if load_handler in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(load_handler)
    
    # Remove timer
    global timer
    if timer and timer in bpy.app.timers.get_timers():
        bpy.app.timers.unregister(timer)
    timer = None
    
    # Unregister classes
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except Exception as e:
            print(f"Error unregistering class: {str(e)}")
    
    print("Save Reminder addon unregistered")

if __name__ == "__main__":
    register()