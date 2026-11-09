from datetime import date, time

from django.core.management.base import BaseCommand
from django.db import transaction

from volunteers.models import Event, Role, Shift

# Name, Spanish name, color, order
ROLES = [
    ("Setup crew", "Equipo de montaje", "#425b76", 10),
    ("Kitchen crew", "Equipo de cocina", "#5f633f", 20),
    ("Greeters and check-in", "Bienvenida y registro", "#7f9cc0", 30),
    ("Serving line", "Línea de servicio", "#a75531", 40),
    ("Meal delivery drivers", "Reparto de comidas", "#1d3249", 50),
    ("Warm clothing table", "Mesa de ropa de abrigo", "#8e905a", 60),
    ("Cleanup crew", "Equipo de limpieza", "#8d9178", 70),
]

EVENT = {
    "name": "Tahoe Community Thanksgiving",
    "name_es": "Día de Acción de Gracias Comunitario de Tahoe",
    "intro": "Help us share a Thanksgiving meal with our neighbors. Choose the shifts that fit your "
             "holiday. No experience needed. A team lead will show you what to do.",
    "intro_es": "Ayúdenos a compartir una comida de Acción de Gracias con nuestros vecinos. Elija los turnos "
                "que mejor le queden en este día festivo. No se necesita experiencia: un líder de equipo le "
                "mostrará qué hacer.",
    "location": "To be announced",
    "location_es": "Por anunciar",
    "check_in": "Check in at the volunteer table 10 minutes before your shift starts.",
    "check_in_es": "Regístrese en la mesa de voluntarios 10 minutos antes de que empiece su turno.",
    "good_to_know": "Wear closed-toe shoes and clothes that can get a little messy.\n"
                    "Ages 14 to 17 are welcome with a parent or guardian on the same shift.\n"
                    "Back-to-back shifts are fine.",
    "good_to_know_es": "Use zapatos cerrados y ropa que se pueda ensuciar un poco.\n"
                       "Los jóvenes de 14 a 17 años son bienvenidos con su padre, madre o tutor en el mismo turno.\n"
                       "Puede elegir turnos seguidos.",
}

WED, THU = date(2026, 11, 25), date(2026, 11, 26)
# Role, day, start, end, volunteers needed, where, what they'll do, tags, then the same three in Spanish
SHIFTS = [
    ("Setup crew", WED, time(14), time(17), 8, "Dining hall",
     "Set up tables, chairs, signs and the serving line.", "Lifting up to 30 lb",
     "Comedor", "Colocar mesas, sillas, letreros y la línea de servicio.", "Levantar hasta 30 lb"),
    ("Kitchen crew", WED, time(15), time(19), 10, "Kitchen",
     "Peel, chop and roast vegetables and get the stuffing ready for tomorrow.", "",
     "Cocina", "Pelar, picar y asar verduras, y dejar listo el relleno para mañana.", ""),
    ("Kitchen crew", THU, time(8), time(11), 10, "Kitchen",
     "Carve turkeys, warm the sides and plate desserts.", "Closed-toe shoes",
     "Cocina", "Cortar los pavos, calentar los acompañamientos y servir los postres.", "Zapatos cerrados"),
    ("Greeters and check-in", THU, time(10, 30), time(13, 30), 4, "Front entrance",
     "Welcome guests, help them find a seat and answer questions.", "Spanish speakers especially welcome",
     "Entrada principal", "Dar la bienvenida a los invitados, ayudarles a encontrar asiento y responder preguntas.",
     "Ideal si habla español"),
    ("Serving line", THU, time(11), time(14), 12, "Dining hall",
     "Serve plates, refill drinks and visit with guests.", "",
     "Comedor", "Servir platos, rellenar bebidas y conversar con los invitados.", ""),
    ("Meal delivery drivers", THU, time(11), time(13), 6, "Kitchen door",
     "Deliver warm meals to neighbors who can’t come in.", "Valid license and your own car",
     "Puerta de la cocina", "Llevar comidas calientes a los vecinos que no pueden venir.",
     "Licencia vigente y auto propio"),
    ("Warm clothing table", THU, time(11), time(14), 4, "Lobby",
     "Help guests choose coats, blankets and hats from donated items.", "",
     "Vestíbulo", "Ayudar a los invitados a elegir abrigos, cobijas y gorros entre las donaciones.", ""),
    ("Cleanup crew", THU, time(14), time(16, 30), 10, "Dining hall and kitchen",
     "Wash dishes, pack leftovers and reset the hall.", "Lifting up to 30 lb",
     "Comedor y cocina", "Lavar los platos, empacar las sobras y dejar el salón listo.", "Levantar hasta 30 lb"),
]


class Command(BaseCommand):
    help = "Adds a sample Thanksgiving volunteer event so you can try the sign-up. Edit or delete it in the admin."

    @transaction.atomic
    def handle(self, *args, **options):
        roles = {}
        for name, name_es, color, order in ROLES:
            roles[name], _ = Role.objects.get_or_create(
                name=name, defaults={"name_es": name_es, "color": color, "order": order})
        event, created = Event.objects.get_or_create(slug="community-thanksgiving-2026", defaults=EVENT)
        if not created:
            self.stdout.write("The sample event already exists. Nothing changed.")
            return
        for role, day, start, end, capacity, where, details, tags, where_es, details_es, tags_es in SHIFTS:
            Shift.objects.create(event=event, role=roles[role], date=day, start=start, end=end,
                                 capacity=capacity, where=where, details=details, tags=tags,
                                 where_es=where_es, details_es=details_es, tags_es=tags_es)
        self.stdout.write(self.style.SUCCESS(
            f"Added “{event.name}” with {len(SHIFTS)} shifts. Change it under Volunteers > Events in the admin."))
