"""Avantage imposable des régimes d'assurance de la construction.

La cotisation PATRONALE aux régimes d'assurance profite au salarié sans lui être
versée : elle constitue pour lui un avantage imposable. Il ne touche pas cet
argent, mais l'impôt du Québec et le RRQ se calculent dessus.

CE MONTANT NE SE CALCULE PAS, IL SE RELÈVE. La tentation est de le dériver de la
cotisation patronale de prévoyance, avec ou sans la taxe de vente — les deux
donnent un chiffre faux. L'avantage ne porte que sur les protections d'assurance
vie et maladie, alors que la cotisation finance toute la caisse de prévoyance,
assurance salaire comprise. Il varie d'ailleurs selon le groupe d'annexes, ce
qu'une cotisation unique ne peut pas produire.

Il dépend du métier, du secteur et du groupe d'annexes, JAMAIS de la période
d'apprentissage : un apprenti de première période et un compagnon reçoivent la
même couverture, donc le même avantage. C'est ce qui l'exclut de la grille des
taux de salaire, organisée par compétence.

Les montants peuvent être révisés en cours de période malgré la date de fin
publiée : ils sont datés comme tous les barèmes, jamais figés dans une constante.
"""

from odoo import fields, models


class CcqAvantageImposable(models.Model):
    _name = 'ccq.avantage.imposable'
    _description = "CCQ — Avantage imposable des régimes d'assurance ($/h)"
    _order = 'date_debut desc, metier_id, secteur_id, annexe_id'

    metier_id = fields.Many2one(
        'ccq.metier', string="Métier", required=True, ondelete='cascade')
    secteur_id = fields.Many2one(
        'ccq.secteur', string="Secteur", required=True, ondelete='cascade')
    annexe_id = fields.Many2one(
        'ccq.annexe', string="Annexe de salaire", required=True, ondelete='cascade')
    date_debut = fields.Date(string="En vigueur le", required=True)
    montant_horaire = fields.Float(
        string="Avantage imposable ($/h)", digits=(12, 4), required=True,
        help="Montant par heure travaillée qui s'ajoute au revenu imposable du "
             "Québec et au salaire admissible au RRQ. Il ne s'ajoute ni au revenu "
             "imposable fédéral, ni au RQAP, ni à l'assurance-emploi, et n'est "
             "jamais versé au salarié.",
    )
    note = fields.Char(string="Note")

    _sql_constraints = [
        ('unicite_combinaison',
         'unique(metier_id, secteur_id, annexe_id, date_debut)',
         "Un seul avantage imposable par métier, secteur, annexe et date d'entrée "
         "en vigueur."),
    ]

    def _montant_applicable(self, metier, secteur, annexe, date):
        """Montant en vigueur à `date` pour la combinaison demandée.

        Retourne l'enregistrement dont la date d'entrée en vigueur est la plus
        récente parmi celles antérieures ou égales à la date des travaux — même
        logique que la grille des taux, donc pas de date de fin à maintenir.

        L'absence d'enregistrement vaut zéro : les montants ne sont publiés que
        pour les combinaisons où un régime d'assurance existe, et une paie
        antérieure au premier millésime chargé n'en portait pas.
        """
        return self.search([
            ('metier_id', '=', metier.id),
            ('secteur_id', '=', secteur.id),
            ('annexe_id', '=', annexe.id),
            ('date_debut', '<=', date),
        ], order='date_debut desc', limit=1)
