from django import forms
from django.forms import inlineformset_factory
from django.utils.text import slugify

from apps.catalogue.models import Product, ProductVariant

MAX_IMAGE_BYTES = 2 * 1024 * 1024
ALLOWED_IMAGE_FORMATS = {"JPEG", "PNG", "WEBP"}


class StockActionForm(forms.Form):
    ACTIONS = [
        ("receive", "Receive stock (add)"),
        ("adjust_up", "Adjust up (found stock)"),
        ("adjust_down", "Adjust down (count correction)"),
        ("waste", "Record waste (spoiled / expired)"),
    ]
    variant = forms.ModelChoiceField(
        queryset=ProductVariant.objects.select_related("product").filter(is_active=True, product__is_active=True)
    )
    action = forms.ChoiceField(choices=ACTIONS)
    quantity = forms.IntegerField(min_value=1, max_value=100000)
    reason = forms.CharField(
        max_length=255,
        required=False,
        help_text="Required for adjustments and waste. Optional when receiving.",
    )

    def clean(self):
        data = super().clean()
        if data.get("action") in ("adjust_up", "adjust_down", "waste") and not (data.get("reason") or "").strip():
            self.add_error("reason", "A reason is required for this action.")
        return data


class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = ["category", "name", "slug", "description", "image", "is_active"]
        widgets = {"description": forms.Textarea(attrs={"rows": 4})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["slug"].required = False
        self.fields["slug"].help_text = "Leave blank to create it from the name."
        self.fields["image"].help_text = "JPEG, PNG or WebP, up to 2 MB."

    def clean_image(self):
        image = self.cleaned_data.get("image")
        if image and hasattr(image, "image"):  # a newly uploaded file (already opened by Pillow)
            if image.size > MAX_IMAGE_BYTES:
                raise forms.ValidationError("Image is too large (maximum 2 MB).")
            if image.image.format not in ALLOWED_IMAGE_FORMATS:
                raise forms.ValidationError("Use a JPEG, PNG or WebP image.")
        return image

    def clean(self):
        data = super().clean()
        name = data.get("name")
        slug = (data.get("slug") or "").strip()
        auto = not slug
        if auto and name:
            slug = slugify(name)
        if not slug:
            if name:
                self.add_error("name", "Use letters or numbers in the name.")
            return data

        def taken(candidate):
            return Product.objects.filter(slug=candidate).exclude(pk=self.instance.pk).exists()

        base, n = slug, 2
        if taken(slug):
            if not auto:
                self.add_error("slug", "That slug is already used by another product.")
                return data
            while taken(f"{base}-{n}"):
                n += 1
            slug = f"{base}-{n}"
        data["slug"] = slug
        return data


VariantFormSet = inlineformset_factory(
    Product,
    ProductVariant,
    fields=("name", "price", "unit", "is_active"),
    extra=1,
    min_num=1,
    validate_min=True,
    can_delete=False,
)