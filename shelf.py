from maya import cmds


def create_shelf_button():
    shelf = cmds.tabLayout("ShelfLayout", query=True, selectTab=True)
    command = "from playblast.ui import show\nshow()"
    return cmds.shelfButton(
        parent=shelf,
        label="Playblast",
        annotation="Open Blueprint Playblast",
        imageOverlayLabel="PB",
        command=command,
        sourceType="python",
    )
