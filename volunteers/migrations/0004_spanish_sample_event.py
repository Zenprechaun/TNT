"""Fills in the Spanish text of the sample Thanksgiving event and its roles.

Only boxes that are still empty are filled, and only where the English is still the sample's
own text, so nothing an admin has written is replaced.

New events start with Spanish versions of the age and agreement statements. Events whose English
statements were changed get empty Spanish boxes instead, so they show the English until someone
writes the Spanish.
"""
from django.db import migrations

AGE_EN = "I’m 18 or older, or I’ll volunteer with my parent or guardian on the same shift."
AGE_ES = "Tengo 18 años o más, o haré el voluntariado con mi padre, madre o tutor en el mismo turno."
AGREE_EN = "I’ll follow the volunteer guidelines and directions from staff on site."
AGREE_ES = "Seguiré las pautas para voluntarios y las indicaciones del personal en el lugar."

ROLES = {
    "Setup crew": "Equipo de montaje",
    "Kitchen crew": "Equipo de cocina",
    "Greeters and check-in": "Bienvenida y registro",
    "Serving line": "Línea de servicio",
    "Meal delivery drivers": "Reparto de comidas",
    "Warm clothing table": "Mesa de ropa de abrigo",
    "Cleanup crew": "Equipo de limpieza",
}

EVENT = {
    "name": ("Tahoe Community Thanksgiving", "Día de Acción de Gracias Comunitario de Tahoe"),
    "intro": (
        "Help us share a Thanksgiving meal with our neighbors. Choose the shifts that fit your "
        "holiday. No experience needed. A team lead will show you what to do.",
        "Ayúdenos a compartir una comida de Acción de Gracias con nuestros vecinos. Elija los turnos "
        "que mejor le queden en este día festivo. No se necesita experiencia: un líder de equipo le "
        "mostrará qué hacer.",
    ),
    "location": ("To be announced", "Por anunciar"),
    "check_in": (
        "Check in at the volunteer table 10 minutes before your shift starts.",
        "Regístrese en la mesa de voluntarios 10 minutos antes de que empiece su turno.",
    ),
    "good_to_know": (
        "Wear closed-toe shoes and clothes that can get a little messy.\n"
        "Ages 14 to 17 are welcome with a parent or guardian on the same shift.\n"
        "Back-to-back shifts are fine.",
        "Use zapatos cerrados y ropa que se pueda ensuciar un poco.\n"
        "Los jóvenes de 14 a 17 años son bienvenidos con su padre, madre o tutor en el mismo turno.\n"
        "Puede elegir turnos seguidos.",
    ),
}

# English text of each sample shift field, and its Spanish.
SHIFT_TEXT = {
    "Dining hall": "Comedor",
    "Kitchen": "Cocina",
    "Front entrance": "Entrada principal",
    "Kitchen door": "Puerta de la cocina",
    "Lobby": "Vestíbulo",
    "Dining hall and kitchen": "Comedor y cocina",
    "Set up tables, chairs, signs and the serving line.":
        "Colocar mesas, sillas, letreros y la línea de servicio.",
    "Peel, chop and roast vegetables and get the stuffing ready for tomorrow.":
        "Pelar, picar y asar verduras, y dejar listo el relleno para mañana.",
    "Carve turkeys, warm the sides and plate desserts.":
        "Cortar los pavos, calentar los acompañamientos y servir los postres.",
    "Welcome guests, help them find a seat and answer questions.":
        "Dar la bienvenida a los invitados, ayudarles a encontrar asiento y responder preguntas.",
    "Serve plates, refill drinks and visit with guests.":
        "Servir platos, rellenar bebidas y conversar con los invitados.",
    "Deliver warm meals to neighbors who can’t come in.":
        "Llevar comidas calientes a los vecinos que no pueden venir.",
    "Help guests choose coats, blankets and hats from donated items.":
        "Ayudar a los invitados a elegir abrigos, cobijas y gorros entre las donaciones.",
    "Wash dishes, pack leftovers and reset the hall.":
        "Lavar los platos, empacar las sobras y dejar el salón listo.",
    "Lifting up to 30 lb": "Levantar hasta 30 lb",
    "Closed-toe shoes": "Zapatos cerrados",
    "Spanish speakers especially welcome": "Ideal si habla español",
    "Valid license and your own car": "Licencia vigente y auto propio",
}


def fill_spanish(apps, schema_editor):
    Event = apps.get_model("volunteers", "Event")
    Role = apps.get_model("volunteers", "Role")
    Shift = apps.get_model("volunteers", "Shift")

    for event in Event.objects.all():
        changed = []
        if event.age_statement != AGE_EN and event.age_statement_es == AGE_ES:
            event.age_statement_es = ""
            changed.append("age_statement_es")
        if event.agreement_statement != AGREE_EN and event.agreement_statement_es == AGREE_ES:
            event.agreement_statement_es = ""
            changed.append("agreement_statement_es")
        if event.slug == "community-thanksgiving-2026":
            for field, (english, spanish) in EVENT.items():
                if getattr(event, field) == english and not getattr(event, f"{field}_es"):
                    setattr(event, f"{field}_es", spanish)
                    changed.append(f"{field}_es")
        if changed:
            event.save(update_fields=changed)

    for role in Role.objects.filter(name__in=ROLES, name_es=""):
        role.name_es = ROLES[role.name]
        role.save(update_fields=["name_es"])

    for shift in Shift.objects.filter(event__slug="community-thanksgiving-2026"):
        changed = []
        for field in ("where", "details"):
            english = getattr(shift, field)
            if english in SHIFT_TEXT and not getattr(shift, f"{field}_es"):
                setattr(shift, f"{field}_es", SHIFT_TEXT[english])
                changed.append(f"{field}_es")
        tags = [t.strip() for t in shift.tags.split(",") if t.strip()]
        if tags and all(t in SHIFT_TEXT for t in tags) and not shift.tags_es:
            shift.tags_es = ", ".join(SHIFT_TEXT[t] for t in tags)
            changed.append("tags_es")
        if changed:
            shift.save(update_fields=changed)


class Migration(migrations.Migration):
    dependencies = [("volunteers", "0003_spanish_text")]

    operations = [migrations.RunPython(fill_spanish, migrations.RunPython.noop)]
