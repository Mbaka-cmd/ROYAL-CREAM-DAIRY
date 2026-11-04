from django.contrib import admin

from .models import Category, Product, ProductVariant


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "is_active", "sort_order")
    list_editable = ("is_active", "sort_order")
    prepopulated_fields = {"slug": ("name",)}
    search_fields = ("name",)


class ProductVariantInline(admin.TabularInline):
    model = ProductVariant
    extra = 1


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "is_active", "updated_at")
    list_filter = ("is_active", "category")
    list_select_related = ("category",)
    prepopulated_fields = {"slug": ("name",)}
    search_fields = ("name",)
    inlines = [ProductVariantInline]


@admin.register(ProductVariant)
class ProductVariantAdmin(admin.ModelAdmin):
    list_display = ("product", "name", "price", "unit", "is_active")
    list_filter = ("is_active",)
    list_select_related = ("product",)
    search_fields = ("name", "product__name")