"""Chantier — le porteur des dimensions de lieu.

Trois des sept dimensions du rapport mensuel vivent ici : le secteur, l'annexe et
la région. Elles sont fixées UNE FOIS à l'ouverture du chantier et ne bougent
plus. C'est ce qui permet au commis de ne saisir que « employé + chantier +
heures » : le reste se reconstitue tout seul.

Le drapeau `assujetti` est l'interrupteur principal de tout le module. Un même
employé peut faire de l'installation sur chantier (assujettie à la loi R-20) et de
l'inspection ou de l'entretien (souvent hors champ) dans la même semaine. Si
l'étiquette est fausse, soit l'entreprise remet à la CCQ pour des heures non
assujetties, soit elle sous-déclare — et le second cas, c'est une vérification
avec intérêts et pénalités.
"""

from odoo import api, fields, models
from odoo.exceptions import ValidationError


class CcqChantier(models.Model):
    _name = 'ccq.chantier'
    _description = "CCQ — Chantier"
    _order = 'name'

    name = fields.Char(string="Nom du chantier", required=True)
    code = fields.Char(string="Numéro de chantier", help="Numéro attribué par la CCQ, s'il y a lieu.")
    partner_id = fields.Many2one(
        'res.partner', string="Donneur d'ouvrage",
        help="Celui qui vous a confié les travaux — le client du projet. Le registre "
             "légal exige les heures ventilées par chantier ET par donneur d'ouvrage "
             "(R-20, article 82 b.0.1) et r. 11, article 8).")

    assujetti = fields.Boolean(
        string="Assujetti à la loi R-20", default=True,
        help="À décocher seulement si les travaux sortent réellement du champ de la loi "
             "R-20, ce qui est rare pour un entrepreneur de la construction. "
             "L'installation des systèmes du bâtiment est de la construction dans tous les "
             "cas ; leur entretien et leur réparation le sont aussi dès qu'ils sont "
             "exécutés par vos propres salariés de la construction, même sous contrat de "
             "service. Le travail fait occasionnellement en atelier reste lui aussi "
             "assujetti. Sources : R-20 art. 1 f) et 19, et R-20, r. 1, art. 1 et 3.",
    )
    secteur_id = fields.Many2one('ccq.secteur', string="Secteur", ondelete='restrict')
    annexe_id = fields.Many2one('ccq.annexe', string="Annexe de salaire", ondelete='restrict')
    region_id = fields.Many2one('ccq.region', string="Région", ondelete='restrict')

    street = fields.Char(string="Adresse")
    city = fields.Char(string="Ville")
    zip = fields.Char(string="Code postal")

    date_ouverture = fields.Date(string="Ouverture")
    date_fermeture = fields.Date(string="Fermeture")

    company_id = fields.Many2one(
        'res.company', string="Société", required=True,
        default=lambda self: self.env.company)
    active = fields.Boolean(default=True)
    note = fields.Text(string="Notes")

    @api.constrains('annexe_id', 'secteur_id')
    def _check_annexe_secteur(self):
        for chantier in self:
            if chantier.annexe_id and chantier.annexe_id.secteur_id != chantier.secteur_id:
                raise ValidationError(
                    "L'annexe « %s » appartient au secteur « %s ». Choisissez une annexe "
                    "du secteur « %s » ou corrigez le secteur du chantier."
                    % (chantier.annexe_id.code,
                       chantier.annexe_id.secteur_id.code,
                       chantier.secteur_id.code or "non défini")
                )

    @api.constrains('assujetti', 'secteur_id', 'annexe_id', 'region_id')
    def _check_dimensions_assujetti(self):
        """Un chantier assujetti incomplet ne peut produire ni paie ni déclaration.

        On bloque à la saisie plutôt qu'au calcul : une feuille de temps rattachée à
        un chantier incomplet donnerait un taux introuvable une semaine plus tard,
        au pire moment.

        La région n'entre dans aucun calcul de salaire, mais c'est l'une des sept
        dimensions du rapport mensuel. Sans elle les heures ne peuvent pas être
        ventilées, et l'information est irrécupérable un mois plus tard.
        """
        for chantier in self:
            if chantier.assujetti and not (chantier.secteur_id and chantier.annexe_id
                                           and chantier.region_id):
                raise ValidationError(
                    "Le chantier « %s » est assujetti à la loi R-20 : son secteur, son "
                    "annexe de salaire et sa région sont obligatoires." % chantier.name
                )

    @api.onchange('secteur_id')
    def _onchange_secteur_id(self):
        """L'annexe dépend du secteur : on la vide dès que le secteur change."""
        if self.annexe_id.secteur_id != self.secteur_id:
            self.annexe_id = False
        return {'domain': {'annexe_id': [('secteur_id', '=', self.secteur_id.id)]}}
