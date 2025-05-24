import customtkinter as ctk
from pyjmine import PyJMine
from pyjmine import Mappings, MappingsType

# Initialize PyJMine
pjm = PyJMine()
pjm.init()

# Define Mappings
print(pjm.version)
mappings = Mappings(
    version=pjm.version,
    mapping_type=MappingsType.MOJANG
)

# Fetch Minecraft classes
minecraft_mappings = mappings.fetch('net.minecraft.client.Minecraft')
Minecraft = pjm.get_class(minecraft_mappings)

entity_mappings = mappings.fetch('net.minecraft.world.entity.Entity')
Entity = pjm.get_class(entity_mappings)

aabb_mappings = mappings.fetch('net.minecraft.world.phys.AABB')
AABB = pjm.get_class(aabb_mappings)

def update_hitboxes(hit_scale=0.6):
    """Update the player's hitbox in Minecraft."""
    minecraft_instance = Minecraft.getInstance()
    print(minecraft_instance)
    if minecraft_instance:
        Minecraft.set_instance(minecraft_instance)
        player_instance = Minecraft.player
        if player_instance:
            Entity.set_instance(player_instance)
            aabb = Entity.getBoundingBox()
            AABB.set_instance(aabb)

            min_x = AABB.minX
            max_x = AABB.maxX

            center_x = (min_x + max_x) / 2.0

            min_y = AABB.minY
            max_y = AABB.maxY

            min_z = AABB.minZ
            max_z = AABB.maxZ

            center_z = (min_z + max_z) / 2.0

            new_half_width = hit_scale / 2.0

            aabb_instance = AABB.jclass(
                center_x - new_half_width,
                min_y,
                center_z - new_half_width,
                center_x + new_half_width,
                max_y,
                center_z + new_half_width
            )

            Entity.setBoundingBox(
                aabb_instance,
                num_params=1,
                param_types=[aabb_mappings.get('obfuscated_class_name')],
                return_type='void'
            )

# Create a simple UI to adjust the hitbox scale
def on_hitbox_scale_change(scale):
    update_hitboxes(hit_scale=float(scale))

# Initialize customtkinter window
root = ctk.CTk()

# Title for the window
root.title("Minecraft Hitbox Adjuster")

# Add a scale widget to adjust the hitbox scale
scale_label = ctk.CTkLabel(root, text="Adjust Hitbox Scale:")
scale_label.pack(pady=10)

hitbox_scale = ctk.CTkSlider(root, from_=0.1, to=2.0, number_of_steps=20, command=on_hitbox_scale_change)
hitbox_scale.set(0.6)  # Set initial value
hitbox_scale.pack(pady=20)

# Run the application
root.mainloop()
